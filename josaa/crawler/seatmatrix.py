"""Crawl the seat matrix (seats available), per institute type.

The seat-matrix page has only three dropdowns (Institute Type, Institute, Program)
— no round, year, seat-type or gender. We loop institute types, pull the full grid,
and tag each row with its type. The grid is parsed by column header; seat counts may
arrive as a single column or split into Gender-Neutral / Female-only columns, both of
which `ingest._persist_seats` handles.
"""
from __future__ import annotations

from typing import Callable, Iterator

from ..config import settings
from ..logging_conf import get_logger
from .browser import Crawler
from .parse import normalize_institute_type, parse_seatmatrix

log = get_logger(__name__)

SEATMATRIX_URL = "https://josaa.admissions.nic.in/applicant/seatmatrix/seatmatrixinfo.aspx"

_P = "ctl00_ContentPlaceHolder1_"
ID = {
    "instype": _P + "ddlInstType",   # note: capital T here (differs from ORCR page)
    "institute": _P + "ddlInstitute",
    "branch": _P + "ddlBranch",
}


def crawl_seatmatrix(
    on_rows: Callable[[dict, list[dict]], None],
    debug_dump: Callable[[str, str], None] | None = None,
) -> Iterator[dict]:
    year = settings.current_year
    with Crawler() as c:
        c.goto(SEATMATRIX_URL)
        type_labels = c.options(ID["instype"])

        for label in type_labels:
            itype = normalize_institute_type(label)
            if itype is None:
                continue

            c.goto(SEATMATRIX_URL)
            if not c.select(ID["instype"], label):
                continue
            c.select(ID["institute"], "ALL")
            c.select(ID["branch"], "ALL")
            c.submit()
            # The result grid (esp. GFTI, ~900 rows / 1.8 MB) can render after
            # networkidle resolves — wait until it has actually populated.
            try:
                c.page.wait_for_selector("table tr:nth-child(40)", timeout=25_000)
            except Exception:
                pass

            html = c.content()
            if debug_dump:
                debug_dump(f"seatmatrix_{year}_{itype}", html)
            records = parse_seatmatrix(html)
            ctx = {"page": "seatmatrix", "year": year, "institute_type": itype}
            on_rows(ctx, records)
            yield {**ctx, "status": "ok", "rows": len(records)}
