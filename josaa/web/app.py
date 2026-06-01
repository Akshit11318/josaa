"""FastAPI backend: serves the static UI and the prediction API."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func

from ..config import settings
from ..db import session_scope, wait_for_db
from ..logging_conf import get_logger
from ..models import Cutoff, Institute, Program, SeatMatrix
from ..predict.deterministic import predict

log = get_logger(__name__)
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="JoSAA Predictor", docs_url="/api/docs")


class PredictRequest(BaseModel):
    exam: str = Field(..., pattern="^(jee_adv|jee_main)$")
    rank: int = Field(..., gt=0)
    gender: str = "male"
    prefs: str = ""
    ai: bool = False


@app.get("/api/meta")
def meta():
    wait_for_db()
    with session_scope() as s:
        years = [r[0] for r in s.query(Cutoff.year).distinct().order_by(Cutoff.year.desc()).all()]
        return {
            "years": years,
            "institutes": s.query(Institute).count(),
            "cutoffs": s.query(Cutoff).count(),
            "seat_rows": s.query(SeatMatrix).count(),
            "current_year": settings.current_year,
            "ai_available": bool(settings.anthropic_api_key),
        }


@app.post("/api/predict")
def api_predict(req: PredictRequest):
    log.info("predict exam=%s rank=%s gender=%s ai=%s", req.exam, req.rank, req.gender, req.ai)
    with session_scope() as s:
        candidates = predict(s, exam=req.exam, rank=req.rank, gender=req.gender)
        data = [asdict(c) for c in candidates]

    counts = {"green": 0, "yellow": 0, "red": 0}
    for c in data:
        counts[c["bucket"]] += 1

    payload: dict = {"candidates": data, "counts": counts, "total": len(data)}

    if req.ai:
        if not settings.anthropic_api_key:
            raise HTTPException(400, "AI requested but ANTHROPIC_API_KEY is not set.")
        from ..predict.ai import refine_with_claude
        log.info("refining %s candidates with Claude (%s)", len(candidates), settings.anthropic_model)
        payload["ai"] = refine_with_claude(
            candidates, exam=req.exam, rank=req.rank, gender=req.gender, preferences=req.prefs)
    return payload


@app.get("/api/trend")
def trend(institute: str, program: str, gender: str, quota: str | None = None):
    """Every (year, round) opening/closing rank for one program — feeds the modal."""
    with session_scope() as s:
        q = (
            s.query(Cutoff.year, Cutoff.round, Cutoff.opening_rank, Cutoff.closing_rank, Cutoff.quota)
            .join(Institute, Cutoff.institute_id == Institute.id)
            .join(Program, Cutoff.program_id == Program.id)
            .filter(Institute.name == institute, Program.name == program,
                    Cutoff.seat_type == "OPEN", Cutoff.gender == gender)
        )
        if quota:
            q = q.filter(Cutoff.quota == quota)
        rows = q.order_by(Cutoff.year, Cutoff.round).all()

    series: dict[str, list] = {}
    for year, rnd, opening, closing, _quota in rows:
        series.setdefault(str(year), []).append(
            {"round": rnd, "opening": opening, "closing": closing})
    return {"institute": institute, "program": program, "gender": gender,
            "quota": quota, "series": series}


@app.get("/")
def index():
    # no-cache so UI updates (new columns, modal) show on refresh without a hard reload
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
