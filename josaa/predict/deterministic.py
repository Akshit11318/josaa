"""Deterministic rank-cutoff prediction.

Given a JEE rank, find programs the candidate can plausibly get and bucket each
into green (safe) / yellow (moderate) / red (reach) by comparing the candidate's
rank to the program's final-round closing rank. Lower rank number = better.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Cutoff, Institute, Program, SeatMatrix

# exam -> institute types whose seats are filled from that rank list
EXAM_TYPES = {
    "jee_adv": ["IIT"],
    "jee_main": ["NIT", "IIIT", "GFTI"],
}

FEMALE_GENDERS = ["Gender-Neutral", "Female-only (including Supernumerary)"]
MALE_GENDERS = ["Gender-Neutral"]

# bucket thresholds on ratio = projected_closing_rank / candidate_rank
GREEN_MIN = 1.20   # closing comfortably worse than you -> safe
YELLOW_MIN = 1.00  # you are inside, but tight -> moderate
RED_MIN = 0.85     # you are slightly worse than closing -> reach
# below RED_MIN -> dropped as out of reach


def _project(trend: dict[int, int], latest_close: int) -> int:
    """Trend-projected closing rank for the upcoming cycle.

    With >=2 years, extrapolate the year-over-year slope one step forward, then
    blend 50/50 with the latest year (conservative — avoids wild extrapolation).
    With one year, just use it.
    """
    yrs = sorted(trend)
    if len(yrs) >= 2:
        span = yrs[-1] - yrs[0]
        slope = (trend[yrs[-1]] - trend[yrs[0]]) / span if span else 0
        projected = trend[yrs[-1]] + slope
        return max(1, int(round(0.5 * projected + 0.5 * latest_close)))
    return latest_close


def _seat_pad(seats: int | None) -> float:
    """Fewer seats -> more volatile cutoff -> demand a bigger safety cushion."""
    if seats is None:
        return 0.0
    if seats <= 3:
        return 0.12
    if seats <= 8:
        return 0.05
    return 0.0


@dataclass
class Candidate:
    institute: str
    institute_type: str
    program: str
    quota: str
    gender: str
    year: int                         # latest data year this cutoff is from
    round: int                        # final round used (max round in that year)
    closing_rank: int                 # latest year's final-round closing rank
    projected_close: int              # trend-projected closing rank (used for bucketing)
    opening_rank: int | None
    bucket: str                       # green | yellow | red
    margin_pct: float                 # (projected-rank)/projected * 100
    seats: int | None = None
    trend: dict[int, int] = field(default_factory=dict)  # year -> final closing rank


def _bucket(rank: int, projected: int, seats: int | None) -> str | None:
    ratio = projected / rank
    pad = _seat_pad(seats)
    if ratio >= GREEN_MIN + pad:
        return "green"
    if ratio >= YELLOW_MIN + pad:
        return "yellow"
    if ratio >= RED_MIN:
        return "red"
    return None


def latest_year(session: Session) -> int | None:
    return session.query(func.max(Cutoff.year)).scalar()


def _final_round_closings(session: Session, year: int, types: list[str], genders: list[str]):
    """Final-round (max round) closing rank per (institute, program, quota, gender)."""
    rows = (
        session.query(Cutoff, Institute.name, Institute.type, Program.name)
        .join(Institute, Cutoff.institute_id == Institute.id)
        .join(Program, Cutoff.program_id == Program.id)
        .filter(
            Cutoff.year == year,
            Institute.type.in_(types),
            Cutoff.gender.in_(genders),
            Cutoff.closing_rank.isnot(None),
        )
        .all()
    )
    best: dict[tuple, tuple] = {}
    for cutoff, iname, itype, pname in rows:
        key = (iname, itype, pname, cutoff.quota, cutoff.gender)
        prev = best.get(key)
        if prev is None or cutoff.round > prev[0].round:
            best[key] = (cutoff, iname, itype, pname)
    return best


def _trends(session: Session, types: list[str], genders: list[str]) -> dict[tuple, dict[int, int]]:
    """For every group, the final-round closing rank in each year (for trend display)."""
    rows = (
        session.query(
            Institute.name, Institute.type, Program.name,
            Cutoff.quota, Cutoff.gender, Cutoff.year, Cutoff.round, Cutoff.closing_rank,
        )
        .join(Institute, Cutoff.institute_id == Institute.id)
        .join(Program, Cutoff.program_id == Program.id)
        .filter(Institute.type.in_(types), Cutoff.gender.in_(genders), Cutoff.closing_rank.isnot(None))
        .all()
    )
    acc: dict[tuple, dict[int, tuple[int, int]]] = {}  # key -> year -> (round, closing)
    for iname, itype, pname, quota, gender, year, rnd, closing in rows:
        key = (iname, itype, pname, quota, gender)
        per_year = acc.setdefault(key, {})
        if year not in per_year or rnd > per_year[year][0]:
            per_year[year] = (rnd, closing)
    return {k: {y: c for y, (_, c) in v.items()} for k, v in acc.items()}


def _seat_lookup(session: Session, year: int) -> dict[tuple, int]:
    """Seats keyed by (institute, program, seat_type, gender) — quota is collapsed
    in the seat matrix, so we don't key on it."""
    rows = (
        session.query(Institute.name, Program.name,
                      SeatMatrix.seat_type, SeatMatrix.gender, SeatMatrix.seats)
        .join(Institute, SeatMatrix.institute_id == Institute.id)
        .join(Program, SeatMatrix.program_id == Program.id)
        .filter(SeatMatrix.year == year)
        .all()
    )
    return {(iname, pname, stype, gender): seats
            for iname, pname, stype, gender, seats in rows}


def predict(
    session: Session,
    exam: str,
    rank: int,
    gender: str = "male",
    include_buckets: tuple[str, ...] = ("green", "yellow", "red"),
) -> list[Candidate]:
    if exam not in EXAM_TYPES:
        raise ValueError(f"exam must be one of {list(EXAM_TYPES)}")
    types = EXAM_TYPES[exam]
    genders = FEMALE_GENDERS if gender.lower().startswith("f") else MALE_GENDERS

    year = latest_year(session)
    if year is None:
        return []

    best = _final_round_closings(session, year, types, genders)
    trends = _trends(session, types, genders)
    seats = _seat_lookup(session, year)

    out: list[Candidate] = []
    for key, (cutoff, iname, itype, pname) in best.items():
        seat_key = (iname, pname, "OPEN", cutoff.gender)
        n_seats = seats.get(seat_key)
        tr = trends.get(key, {})
        projected = _project(tr, cutoff.closing_rank)
        bucket = _bucket(rank, projected, n_seats)
        if bucket is None or bucket not in include_buckets:
            continue
        out.append(Candidate(
            institute=iname,
            institute_type=itype,
            program=pname,
            quota=cutoff.quota,
            gender=cutoff.gender,
            year=cutoff.year,
            round=cutoff.round,
            closing_rank=cutoff.closing_rank,
            projected_close=projected,
            opening_rank=cutoff.opening_rank,
            bucket=bucket,
            margin_pct=round((projected - rank) / projected * 100, 1),
            seats=n_seats,
            trend=tr,
        ))

    order = {"green": 0, "yellow": 1, "red": 2}
    out.sort(key=lambda c: (order[c.bucket], c.projected_close))
    return out
