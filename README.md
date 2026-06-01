# JoSAA branch predictor

Predicts which engineering branches a JEE rank can realistically get, from JoSAA's
publicly published **opening/closing ranks** and **seat matrix**. Each option is
bucketed **🟢 Safe / 🟡 Moderate / 🔴 Reach** using a trend-projected cutoff and the
available seats. Click any row for **year-wise & round-wise** trend charts.

The site is **fully static** — it ships a SQLite snapshot and runs everything in the
browser (via [sql.js](https://sql.js.org/)), so it can be hosted on **GitHub Pages**
with no backend.

## How it works (two phases)

**1. Scrape → Postgres → SQLite (local, Docker).** A Playwright crawler drives the
JoSAA ASP.NET pages, stores cutoffs + seat matrix in Postgres, then exports a compact
`docs/data/josaa.sqlite`.

**2. Static site (`docs/`, GitHub Pages).** `index.html` + `style.css` + `app.js` load
the SQLite in-browser and run the prediction/trend queries client-side. No server.

Scope: Seat Type = **OPEN**, both genders (Gender-Neutral + Female-only incl.
Supernumerary), all rounds, years **2023–2025**, institute types **IIT / NIT / IIIT / GFTI**.

## Data sources
| Data | Page |
|------|------|
| Opening/Closing ranks (all years) | `applicant/seatmatrix/openingclosingrankarchieve.aspx` |
| Seat matrix | `applicant/seatmatrix/seatmatrixinfo.aspx` |

Both are ASP.NET WebForms using the jQuery "Chosen" plugin (hidden `<select>`s driven
by `__doPostBack`); the crawler selects by stable control id with `force=True`.

## Refresh the data (Docker)
```bash
cp .env.example .env
make up            # postgres + a static server for docs/ on :8000
make migrate       # create tables (first time only)
make crawl         # scrape ORCR (2023–2025) + seat matrix  (~15 min)
make export        # write docs/data/josaa.sqlite
make stats         # row counts
```
Preview locally at **http://localhost:8000** — the exact files Pages will serve.

## Deploy to GitHub Pages
The repo includes `.github/workflows/pages.yml`, which publishes `docs/` on every push.

```bash
git init && git add -A && git commit -m "JoSAA predictor"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```
Then in the repo: **Settings → Pages → Source = "GitHub Actions"**. The site goes live
at `https://<you>.github.io/<repo>/`. (No build step needed — the committed
`docs/data/josaa.sqlite` is the data.)

To update the live data later: `make crawl && make export`, then commit `docs/` and push.

## Prediction logic
`ratio = projected_closing / your_rank` (lower rank = better), where the projected
closing rank extrapolates the 3-year trend and is widened when seats are few:
- `≥ 1.20` → 🟢 Safe · `1.00–1.20` → 🟡 Moderate · `0.85–1.00` → 🔴 Reach · below → dropped.

JEE Advanced → IITs; JEE Main → NIT / IIIT / GFTI (with a per-type filter). Female
candidates also see Female-only (incl. Supernumerary) seats. Thresholds live in both
`josaa/predict/deterministic.py` (server) and `docs/app.js` (client, kept in sync).

## SQLite schema (`docs/data/josaa.sqlite`)
- `institutes(id, name, type)` · `programs(id, name)`
- `cutoffs(year, round, institute_id, program_id, quota, gender, opening_rank, closing_rank)`
- `seat_matrix(institute_id, program_id, gender, seats)` — OPEN seats; the branch→seats map

## Notes & limitations
- CurrentORCR.aspx is the *upcoming* (empty) cycle, so all data comes from the archive.
- Quota (AI/HS/OS) is stored and shown; seats are summed across pools per program.
- AI refinement was removed (the static site has no backend). The crawler/predictor
  Python remains for the scrape+export pipeline.
- Guidance only — verify against the official JoSAA site before making choices.
