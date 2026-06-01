from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from .config import settings
from .db import session_scope, wait_for_db
from .ingest import ingest_orcr, ingest_seatmatrix
from .logging_conf import setup_logging
from .models import Cutoff, Institute, SeatMatrix
from .predict.deterministic import predict

app = typer.Typer(add_completion=False, help="JoSAA crawler + rank-based branch predictor.")
console = Console()


@app.callback()
def _init(log_level: str = typer.Option("INFO", "--log-level", help="DEBUG/INFO/WARNING")):
    setup_logging(log_level)

_BUCKET_STYLE = {"green": "bold green", "yellow": "bold yellow", "red": "bold red"}


@app.command()
def crawl(
    years: str = typer.Option("2025,2024,2023", help="Comma-separated years for ORCR."),
    orcr: bool = typer.Option(True, help="Crawl opening/closing ranks."),
    seats: bool = typer.Option(True, help="Crawl the current-year seat matrix."),
):
    """Crawl JoSAA and store OPEN-seat cutoffs (both genders) + seat matrix."""
    yrs = [int(y) for y in years.split(",") if y.strip()]
    if orcr:
        console.print(f"[cyan]Crawling ORCR for years: {yrs}[/cyan]")
        ingest_orcr(yrs)
    if seats:
        console.print(f"[cyan]Crawling seat matrix for {settings.current_year}[/cyan]")
        ingest_seatmatrix()
    console.print("[green]Done.[/green]")


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000):
    """Run the web UI + API (http://localhost:8000)."""
    import uvicorn
    console.print(f"[cyan]Serving JoSAA Predictor on http://localhost:{port}[/cyan]")
    uvicorn.run("josaa.web.app:app", host=host, port=port)


@app.command()
def stats():
    """Show what's in the database."""
    wait_for_db()
    with session_scope() as s:
        console.print(f"Institutes : {s.query(Institute).count()}")
        console.print(f"Cutoffs    : {s.query(Cutoff).count()}")
        console.print(f"Seat rows  : {s.query(SeatMatrix).count()}")
        years = [r[0] for r in s.query(Cutoff.year).distinct().order_by(Cutoff.year).all()]
        console.print(f"Years      : {years}")


@app.command(name="predict")
def predict_cmd(
    exam: str = typer.Option(..., "--exam", help="jee_adv (IITs) or jee_main (NIT/IIIT/GFTI)."),
    rank: int = typer.Option(..., "--rank", help="Category rank (CRL for OPEN)."),
    gender: str = typer.Option("male", "--gender", help="male | female (female unlocks supernumerary seats)."),
    prefs: str = typer.Option("", "--prefs", help="Free-text preferences for the AI recommender."),
    ai: bool = typer.Option(False, "--ai/--no-ai", help="Use Claude to refine & explain the shortlist."),
    limit: int = typer.Option(50, help="Max rows to display for the deterministic table."),
):
    """Predict reachable branches for a JEE rank, bucketed red/yellow/green."""
    wait_for_db()
    with session_scope() as s:
        candidates = predict(s, exam=exam, rank=rank, gender=gender)

        if not candidates:
            console.print("[red]No candidates. Has the crawler been run? Check `stats`.[/red]")
            raise typer.Exit(1)

        table = Table(title=f"{exam} rank {rank} ({gender}) — reachable OPEN seats")
        table.add_column("Bucket")
        table.add_column("Type")
        table.add_column("Institute")
        table.add_column("Program", max_width=40)
        table.add_column("Gender", max_width=14)
        table.add_column("Yr", justify="right")
        table.add_column("Rd", justify="right")
        table.add_column("Closing", justify="right")
        table.add_column("Proj", justify="right")
        table.add_column("Seats", justify="right")
        table.add_column("Trend")

        for c in candidates[:limit]:
            trend = " ".join(f"{y}:{r}" for y, r in sorted(c.trend.items()))
            table.add_row(
                f"[{_BUCKET_STYLE[c.bucket]}]{c.bucket.upper()}[/]",
                c.institute_type, c.institute.replace("  ", " "), c.program,
                c.gender.replace(" (including Supernumerary)", "*"),
                str(c.year), f"R{c.round}",
                str(c.closing_rank), str(c.projected_close), str(c.seats or "-"), trend,
            )
        console.print(table)
        console.print(f"[dim]{len(candidates)} total reachable; showing {min(limit, len(candidates))}.[/dim]")

        if ai:
            from .predict.ai import refine_with_claude
            console.print("\n[cyan]Asking Claude to refine the shortlist...[/cyan]")
            result = refine_with_claude(candidates, exam=exam, rank=rank, gender=gender, preferences=prefs)
            console.print(f"\n[bold]Summary:[/bold] {result.get('summary', '')}\n")
            ai_table = Table(title="Claude shortlist")
            ai_table.add_column("Label")
            ai_table.add_column("Institute")
            ai_table.add_column("Program", max_width=42)
            ai_table.add_column("Reason", max_width=50)
            for pick in result.get("shortlist", []):
                lbl = pick.get("label", "")
                ai_table.add_row(
                    f"[{_BUCKET_STYLE.get(lbl, 'white')}]{lbl.upper()}[/]",
                    pick.get("institute", ""), pick.get("program", ""), pick.get("reason", ""),
                )
            console.print(ai_table)


if __name__ == "__main__":
    app()
