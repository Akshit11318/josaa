"""Persist crawled rows into Postgres with idempotent upserts."""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .crawler.orcr import crawl_orcr
from .crawler.parse import canon, parse_rank
from .crawler.seatmatrix import crawl_seatmatrix
from .db import SessionLocal, session_scope, wait_for_db
from .logging_conf import get_logger
from .models import CrawlRun, Cutoff, Institute, Program, SeatMatrix

log = get_logger(__name__)
DEBUG_DIR = Path("debug_html")


def _debug_dump(name: str, html: str) -> None:
    if os.getenv("DUMP_HTML"):
        DEBUG_DIR.mkdir(exist_ok=True)
        (DEBUG_DIR / f"{name}.html").write_text(html, encoding="utf-8")


class _Cache:
    """In-process get-or-create cache for institutes/programs to cut round-trips."""

    def __init__(self, session: Session):
        self.s = session
        self.inst: dict[str, int] = {}
        self.prog: dict[str, int] = {}

    def institute_id(self, name: str, itype: str) -> int:
        name = canon(name)
        if name in self.inst:
            return self.inst[name]
        obj = self.s.query(Institute).filter_by(name=name).one_or_none()
        if obj is None:
            obj = Institute(name=name, type=itype)
            self.s.add(obj)
            self.s.flush()
        elif obj.type != itype and itype:
            obj.type = itype
        self.inst[name] = obj.id
        return obj.id

    def program_id(self, name: str) -> int:
        name = canon(name)
        if name in self.prog:
            return self.prog[name]
        obj = self.s.query(Program).filter_by(name=name).one_or_none()
        if obj is None:
            obj = Program(name=name)
            self.s.add(obj)
            self.s.flush()
        self.prog[name] = obj.id
        return obj.id


def _persist_cutoffs(session: Session, cache: _Cache, ctx: dict, rows: list[dict]) -> int:
    n = 0
    for r in rows:
        inst_name = r.get("institute")
        prog_name = r.get("program")
        if not inst_name or not prog_name:
            continue
        seat_type = (r.get("seat_type") or ctx.get("seat_type") or "").strip()
        if seat_type.upper() != "OPEN":   # defensive: keep only OPEN
            continue

        o_raw, o_int = parse_rank(r.get("opening_rank"))
        c_raw, c_int = parse_rank(r.get("closing_rank"))
        values = dict(
            year=ctx["year"],
            round=ctx["round"],
            institute_id=cache.institute_id(inst_name, ctx["institute_type"]),
            program_id=cache.program_id(prog_name),
            quota=(r.get("quota") or "").strip() or "AI",
            seat_type="OPEN",
            gender=(r.get("gender") or "").strip() or "Gender-Neutral",
            opening_rank=o_int,
            closing_rank=c_int,
            opening_rank_raw=o_raw,
            closing_rank_raw=c_raw,
        )
        stmt = pg_insert(Cutoff).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_cutoff",
            set_={
                "opening_rank": stmt.excluded.opening_rank,
                "closing_rank": stmt.excluded.closing_rank,
                "opening_rank_raw": stmt.excluded.opening_rank_raw,
                "closing_rank_raw": stmt.excluded.closing_rank_raw,
            },
        )
        session.execute(stmt)
        n += 1
    return n


def _persist_seats(session: Session, cache: _Cache, ctx: dict, records: list[dict]) -> int:
    """records come from parse_seatmatrix: {institute, program, gn_seats, female_seats}.
    Stored with quota="ALL" (OPEN seats summed across pools); the prediction joins
    on (institute, program, seat_type, gender), ignoring quota."""
    n = 0
    for r in records:
        iid = cache.institute_id(r["institute"], ctx["institute_type"])
        pid = cache.program_id(r["program"])
        for gender, seats in (
            ("Gender-Neutral", r.get("gn_seats", 0)),
            ("Female-only (including Supernumerary)", r.get("female_seats", 0)),
        ):
            stmt = pg_insert(SeatMatrix).values(
                year=ctx["year"], institute_id=iid, program_id=pid,
                quota="ALL", seat_type="OPEN", gender=gender, seats=seats or 0)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_seat_matrix", set_={"seats": stmt.excluded.seats})
            session.execute(stmt)
            n += 1
    return n


def ingest_orcr(years: list[int]) -> None:
    wait_for_db()
    log.info("[bold]Starting ORCR crawl[/bold] for years %s (OPEN, both genders)", years)
    total = 0
    # One long-lived session, but committed after EACH crawl unit so rows appear
    # live in the UI and a mid-crawl crash keeps everything already fetched.
    session = SessionLocal()
    cache = _Cache(session)

    def on_rows(ctx: dict, rows: list[dict]) -> None:
        try:
            count = _persist_cutoffs(session, cache, ctx, rows)
            session.add(CrawlRun(page="orcr", year=ctx["year"], round=ctx["round"],
                                 institute_type=ctx["institute_type"], status="ok", rows=count))
            session.commit()
        except Exception:
            session.rollback()
            raise

    try:
        for status in crawl_orcr(years, on_rows, _debug_dump):
            if status.get("status") == "ok":
                total += status.get("rows", 0)
                log.info("  ORCR %s round %s %-4s -> %s rows kept (running total %s)",
                         status["year"], status["round"], status["institute_type"],
                         status["rows"], total)
            else:
                log.warning("  ORCR %s: %s", status.get("year"), status.get("message"))
    finally:
        session.close()
    log.info("[green]ORCR crawl done[/green] — %s cutoff rows upserted", total)


def ingest_seatmatrix() -> None:
    wait_for_db()
    from .config import settings
    log.info("[bold]Starting seat-matrix crawl[/bold] for %s", settings.current_year)
    total = 0
    session = SessionLocal()
    cache = _Cache(session)

    def on_rows(ctx: dict, rows: list[dict]) -> None:
        try:
            count = _persist_seats(session, cache, ctx, rows)
            session.add(CrawlRun(page="seatmatrix", year=ctx["year"], round=None,
                                 institute_type=ctx["institute_type"], status="ok", rows=count))
            session.commit()
        except Exception:
            session.rollback()
            raise

    try:
        for status in crawl_seatmatrix(on_rows, _debug_dump):
            total += status.get("rows", 0)
            log.info("  Seats %-4s -> %s rows", status["institute_type"], status["rows"])
    finally:
        session.close()
    log.info("[green]Seat-matrix crawl done[/green] — %s seat rows upserted", total)
