"""Crawl opening/closing ranks (OPEN seat type, both genders, all rounds).

As of the 2026-27 cycle, CurrentORCR.aspx serves the not-yet-run 2026 year (empty),
and ALL past years (2025, 2024, 2023, ...) live on the archive page's Year dropdown.
So we drive the archive page exclusively.

Cascade (each step is a full ASP.NET postback): Year -> Round -> Institute Type ->
Institute -> Program -> Seat Type -> Submit. There is no Gender dropdown; Gender is
a column in the result grid, so we read it there. We iterate institute types
explicitly to tag every row with a reliable type for grouping.
"""
from __future__ import annotations

from typing import Callable, Iterator

from ..logging_conf import get_logger
from .browser import Crawler
from .parse import normalize_institute_type, parse_grid

log = get_logger(__name__)

ARCHIVE_URL = "https://josaa.admissions.nic.in/applicant/seatmatrix/openingclosingrankarchieve.aspx"

_P = "ctl00_ContentPlaceHolder1_"
ID = {
    "year": _P + "ddlYear",
    "round": _P + "ddlroundno",
    "instype": _P + "ddlInstype",
    "institute": _P + "ddlInstitute",
    "branch": _P + "ddlBranch",
    "seattype": _P + "ddlSeatType",
}
SEAT_TYPE = "OPEN"


def crawl_orcr(
    years: list[int],
    on_rows: Callable[[dict, list[dict]], None],
    debug_dump: Callable[[str, str], None] | None = None,
) -> Iterator[dict]:
    with Crawler() as c:
        for year in years:
            c.goto(ARCHIVE_URL)
            if not c.select(ID["year"], str(year)):
                yield {"year": year, "status": "error", "message": f"year {year} not in dropdown"}
                continue

            rounds = [o for o in c.options(ID["round"]) if o.strip().isdigit()]
            if not rounds:
                yield {"year": year, "status": "error", "message": "no rounds found"}
                continue
            log.info("Year %s: rounds %s", year, rounds)

            for rnd in rounds:
                # Re-establish a clean state for each round.
                c.goto(ARCHIVE_URL)
                c.select(ID["year"], str(year))
                c.select(ID["round"], rnd)

                type_labels = c.options(ID["instype"])
                for label in type_labels:
                    itype = normalize_institute_type(label)
                    if itype is None:
                        continue

                    if not c.select(ID["instype"], label):
                        continue
                    c.select(ID["institute"], "ALL")
                    c.select(ID["branch"], "ALL")
                    if not c.select(ID["seattype"], SEAT_TYPE):
                        # Seat type populates after Branch; retry once.
                        c.select(ID["branch"], "ALL")
                        c.select(ID["seattype"], SEAT_TYPE)
                    c.submit()

                    html = c.content()
                    if debug_dump:
                        debug_dump(f"orcr_{year}_r{rnd}_{itype}", html)
                    rows = parse_grid(html)
                    ctx = {"page": "orcr", "year": year, "round": int(rnd),
                           "institute_type": itype, "seat_type": SEAT_TYPE}
                    on_rows(ctx, rows)
                    yield {**ctx, "status": "ok", "rows": len(rows)}
