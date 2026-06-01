"""Parse JoSAA ASP.NET GridView result tables into normalised dict rows.

The pages render results as an HTML <table> (an ASP.NET GridView). We parse by
*column header text* rather than by fixed positions / control IDs, so the same
code works for CurrentORCR, the archive page, and the seat matrix even as their
markup shifts year to year.
"""
from __future__ import annotations

import io
import re

from bs4 import BeautifulSoup


def canon(name: str) -> str:
    """Collapse internal whitespace so institute/program names join across pages.
    (The site emits stray double-spaces, inconsistently between the ORCR and
    seat-matrix tables.)"""
    return re.sub(r"\s+", " ", (name or "")).strip()

# Map raw header text (lowercased, collapsed) -> canonical key.
_HEADER_ALIASES = {
    "institute": "institute",
    "academic program name": "program",
    "academic program": "program",
    "program": "program",
    "quota": "quota",
    "seat type": "seat_type",
    "gender": "gender",
    "opening rank": "opening_rank",
    "closing rank": "closing_rank",
    # seat matrix variants
    "total seats": "seats",
    "seats": "seats",
    "gender-neutral": "seats_gn",
    "female-only (including supernumerary)": "seats_female",
    "female-only(including supernumerary)": "seats_female",
}


def _norm_header(text: str) -> str:
    key = re.sub(r"\s+", " ", text or "").strip().lower()
    return _HEADER_ALIASES.get(key, key)


def normalize_institute_type(label: str) -> str | None:
    """Map an institute-type dropdown label to a canonical type.

    Handles both the archive's full names ("Indian Institute of Technology",
    "National Institute of Technology", "Indian Institute of Information
    Technology", "Government Funded Technical Institutions") and the seat-matrix
    abbreviations ("IITs", "NITs", "III-Ts", "GFTIs"). Order matters: IIIT
    (Information Technology) is checked before IIT. Returns None for ALL/--Select--.
    """
    s = (label or "").upper().strip()
    if not s or "SELECT" in s or s == "ALL":
        return None
    if "INFORMATION TECHNOLOGY" in s or "IIIT" in s or "III-T" in s or "III T" in s:
        return "IIIT"
    if "NATIONAL INSTITUTE" in s or "NIT" in s:
        return "NIT"
    if "INDIAN INSTITUTE OF TECHNOLOGY" in s or "IIT" in s:
        return "IIT"
    if "GOVERNMENT FUNDED" in s or "GFTI" in s or "OTHER" in s:
        return "GFTI"
    return None


def parse_rank(raw: str | None) -> tuple[str | None, int | None]:
    """Return (raw_clean, int_value). Ranks may carry a trailing 'P' (preparatory)."""
    if raw is None:
        return None, None
    s = raw.strip()
    if not s or s in {"-", "--"}:
        return None, None
    digits = re.sub(r"[^0-9]", "", s)
    return s, (int(digits) if digits else None)


def parse_int(raw: str | None) -> int | None:
    if not raw:
        return None
    digits = re.sub(r"[^0-9]", "", raw)
    return int(digits) if digits else None


def _pick_result_table(soup: BeautifulSoup):
    """Choose the GridView: prefer a <table> whose id mentions grid; else the
    table with the most rows."""
    tables = soup.find_all("table")
    candidates = [t for t in tables if "grid" in (t.get("id") or "").lower()]
    pool = candidates or tables
    if not pool:
        return None
    return max(pool, key=lambda t: len(t.find_all("tr")))


def parse_grid(html: str) -> list[dict]:
    """Return a list of {canonical_header: cell_text} dicts from the result grid."""
    soup = BeautifulSoup(html, "lxml")
    table = _pick_result_table(soup)
    if table is None:
        return []

    rows = table.find_all("tr")
    if len(rows) < 2:
        return []

    headers = [_norm_header(c.get_text()) for c in rows[0].find_all(["th", "td"])]
    if not any(h in {"institute", "program"} for h in headers):
        return []

    out: list[dict] = []
    for tr in rows[1:]:
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if not cells or len(cells) < 2:
            continue
        record = {headers[i]: cells[i] for i in range(min(len(headers), len(cells)))}
        out.append(record)
    return out


def _to_int(v) -> int:
    """Leading integer of a cell. Handles floats (32.0 -> 32, NOT 320) and jammed
    cells like '90  0' (-> 90)."""
    if v is None:
        return 0
    if isinstance(v, bool):
        return 0
    if isinstance(v, (int, float)):
        try:
            return 0 if (isinstance(v, float) and v != v) else int(v)  # v!=v => NaN
        except (ValueError, OverflowError):
            return 0
    m = re.match(r"\s*(\d+)", str(v))
    return int(m.group(1)) if m else 0


def parse_seatmatrix(html: str) -> list[dict]:
    """Parse the wide seat-matrix grid into per-(institute, program) OPEN seat
    counts. Returns dicts: {institute, program, gn_seats, female_seats}.

    Layout (per program): a Gender-Neutral row carrying institute/program and the
    OPEN count, followed by a column-shifted "Female-only (including Supernumerary)"
    row (institute/program/quota cells dropped, so everything shifts left by 3).
    We sum the GN OPEN across seat pools (Home/Other State) and read the female
    row's OPEN via the shift, attaching it to the preceding program.
    """
    import pandas as pd

    try:
        tables = pd.read_html(io.StringIO(html))
    except (ValueError, ImportError):
        return []

    target = flat = None
    for df in tables:
        cols = [" ".join(str(x) for x in (c if isinstance(c, tuple) else (c,))).lower()
                for c in df.columns]
        if any("institute name" in c for c in cols) and any(c.startswith("open") for c in cols):
            target, flat = df, cols
            break
    if target is None:
        return []

    def find(pred):
        for i, name in enumerate(flat):
            if pred(name):
                return i
        return None

    i_inst = find(lambda s: "institute name" in s)
    i_prog = find(lambda s: "program name" in s)
    i_pool = find(lambda s: "seat pool" in s)
    i_open = find(lambda s: s.startswith("open") and "pwd" not in s)
    if None in (i_inst, i_prog, i_pool, i_open):
        return []
    i_fem_open = i_open - 3  # female row is shifted left by the 3 dropped cells

    agg: dict[tuple, dict] = {}
    last_key = None
    for row in target.itertuples(index=False):
        vals = list(row)
        c0 = str(vals[i_inst]).strip()
        pool = str(vals[i_pool]).strip()

        if c0.lower().startswith("female-only"):
            # shifted female-only row -> attach OPEN seats to the preceding program
            if last_key is not None and i_fem_open >= 0:
                agg[last_key]["fem"] += _to_int(vals[i_fem_open])
            continue

        if pool != "Gender-Neutral":
            continue
        inst, prog = canon(c0), canon(str(vals[i_prog]))
        if not inst or inst.lower() == "nan" or not prog or prog.lower() == "nan":
            continue
        key = (inst, prog)
        agg.setdefault(key, {"gn": 0, "fem": 0})["gn"] += _to_int(vals[i_open])
        last_key = key

    return [{"institute": k[0], "program": k[1], "gn_seats": v["gn"], "female_seats": v["fem"]}
            for k, v in agg.items()]
