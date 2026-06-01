"""Export the scraped Postgres data into a compact SQLite file for the static
(GitHub Pages) site. The browser reads this via sql.js.

Only the columns the client needs are exported (raw rank strings, timestamps and
the always-constant seat_type/quota/year on seat_matrix are dropped to shrink it).

Run after crawling:  python export_sqlite.py
Output:              docs/data/josaa.sqlite
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from josaa.db import engine as pg
from josaa.logging_conf import get_logger

log = get_logger("export")

OUT = Path("docs/data/josaa.sqlite")

QUERIES = {
    "institutes": "SELECT id, name, type FROM institutes",
    "programs": "SELECT id, name FROM programs",
    "cutoffs": (
        "SELECT year, round, institute_id, program_id, quota, gender, "
        "opening_rank, closing_rank FROM cutoffs WHERE closing_rank IS NOT NULL"
    ),
    "seat_matrix": (
        "SELECT institute_id, program_id, gender, seats FROM seat_matrix"
    ),
}

INDEXES = [
    "CREATE INDEX ix_c_type ON cutoffs(institute_id, program_id, gender)",
    "CREATE INDEX ix_c_year ON cutoffs(year, round)",
    "CREATE INDEX ix_s_key ON seat_matrix(institute_id, program_id, gender)",
    "CREATE INDEX ix_i_type ON institutes(type)",
]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    sqlite = create_engine(f"sqlite:///{OUT}")

    total = 0
    for table, q in QUERIES.items():
        df = pd.read_sql_query(text(q), pg)
        df.to_sql(table, sqlite, if_exists="replace", index=False)
        total += len(df)
        log.info("exported %-12s %6d rows", table, len(df))

    with sqlite.begin() as c:
        for stmt in INDEXES:
            c.exec_driver_sql(stmt)
        c.exec_driver_sql("VACUUM")

    size_mb = OUT.stat().st_size / 1e6
    log.info("[green]wrote %s[/green] (%d rows, %.1f MB)", OUT, total, size_mb)


if __name__ == "__main__":
    main()
