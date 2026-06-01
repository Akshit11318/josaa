"""Claude-powered refinement of the deterministic candidate list.

The deterministic pass produces a candidate list with green/yellow/red buckets.
Claude re-weighs them against the candidate's stated preferences (branch interest,
location, risk appetite) and the multi-year trend, then returns a final ordered
shortlist with a red/yellow/green label and a one-line reason per pick.
"""
from __future__ import annotations

import json

from ..config import settings
from .deterministic import Candidate

SYSTEM = (
    "You are a JoSAA counselling advisor for Indian engineering admissions (IITs via "
    "JEE Advanced; NITs/IIITs/GFTIs via JEE Main). You are given a candidate profile and "
    "a pre-filtered list of programs, each already bucketed by a deterministic rank-cutoff "
    "rule into green (safe), yellow (moderate), red (reach). Your job: produce a final, "
    "ordered shortlist tailored to the candidate's preferences and the year-over-year "
    "closing-rank trend.\n\n"
    "Each candidate row is a compact JSON object with keys: i=institute, t=type, "
    "p=program, q=quota, g=gender (GN=gender-neutral, F=female-only incl. supernumerary), "
    "c=trend-projected closing rank, b=deterministic bucket, s=seats, y=closing rank by year.\n\n"
    "Rules:\n"
    "- green = very likely to get; yellow = realistic but not guaranteed; red = reach.\n"
    "- A loosening trend in y (closing ranks rising over years) can upgrade optimism; a "
    "tightening trend (falling) should make you more conservative. Few seats (s) = more volatile.\n"
    "- Respect the candidate's branch and location preferences when ordering.\n"
    "- Never invent institutes/programs not in the provided list.\n"
    "- Reply with ONLY a JSON object, no prose. Keep reasons under 12 words."
)

OUTPUT_SHAPE = (
    '{"summary": "<2-3 sentence overview>", '
    '"shortlist": [{"institute": "...", "program": "...", "quota": "...", '
    '"gender": "...", "label": "green|yellow|red", "reason": "<one line>"}]}'
)


def _select_for_ai(candidates: list[Candidate], max_n: int = 40) -> list[Candidate]:
    """Send Claude only the decision-relevant rows: every yellow/red (the
    borderline calls) plus the best greens, capped — keeps the prompt small."""
    boundary = [c for c in candidates if c.bucket != "green"]
    greens = [c for c in candidates if c.bucket == "green"]
    picked = boundary + greens[: max(0, max_n - len(boundary))]
    return picked[:max_n]


def _candidates_payload(candidates: list[Candidate]) -> str:
    # Compact keys + only the fields Claude needs -> far fewer tokens.
    # i=institute, t=type, p=program, g=gender, c=projected close, b=bucket,
    # s=seats, y=trend (closing by year).
    return json.dumps([
        {"i": c.institute, "t": c.institute_type, "p": c.program, "q": c.quota,
         "g": "F" if c.gender.startswith("Female") else "GN",
         "c": c.projected_close, "b": c.bucket, "s": c.seats,
         "y": {str(k): v for k, v in sorted(c.trend.items())}}
        for c in candidates
    ], ensure_ascii=False, separators=(",", ":"))


def refine_with_claude(
    candidates: list[Candidate],
    exam: str,
    rank: int,
    gender: str,
    preferences: str = "",
    max_picks: int = 20,
) -> dict:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set — run with --no-ai or set the key.")

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    # Only send the decision-relevant subset -> small prompt, low token cost.
    subset = _select_for_ai(candidates)

    profile = (
        f"Exam: {exam}\nRank: {rank}\nGender: {gender}\n"
        f"Preferences: {preferences or '(none stated)'}\n"
        f"Return at most {max_picks} picks, best first.\n"
        f"Respond as JSON exactly matching: {OUTPUT_SHAPE}"
    )

    resp = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1500,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{
            "role": "user",
            "content": [
                # The candidate dataset is the large, reusable block -> cache it so
                # re-running with different preferences is cheap.
                {"type": "text",
                 "text": "Candidate programs (JSON):\n" + _candidates_payload(subset),
                 "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": profile},
            ],
        }],
    )

    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"summary": "Could not parse model output.", "raw": text, "shortlist": []}
