# Infineon Cost & Treasury Agent — Backend

A **decision agent on top of the [Sybilion](https://sybilion.dev/docs/) probabilistic
forecasting API**, built for the Sybilion hackathon (Forecasting AI track) by **Team 43 Food**
(Elliot Sezalory, Fridolin Sitter).

It plays cost & treasury for a European power-semiconductor maker (Infineon): the company's
inputs price in USD but it reports in EUR, so **FX, wholesale power, and commodity
cost-drivers** all move margin. The agent scopes which of those exposures matter, forecasts
them through Sybilion, keeps only the high-confidence signals, turns each into a concrete
action (FX hedge, power hedge, or safety-stock buffer), and **walk-forward backtests every
recommendation on real data**.

Sybilion provides the forecast as an API — our contribution is the layer on top: confidence
scoring from the probability bands, decision rules per exposure type, walk-forward
validation, and a shock engine that re-decides when an assumption shifts mid-run.

> Full technical write-up — problem, approach, results, honest caveats — in **[REPORT.md](REPORT.md)**.

## What it covers

| Exposure | Driver series | Decision the agent makes |
|---|---|---|
| **FX** | 28 major pairs (FRED, EUR-based for Infineon) | BUY/SELL forward hedge on high-confidence pairs |
| **Power** | Austria day-ahead wholesale power | hedge / lock when bands say act |
| **Commodities** | Copper, TTF gas (World Bank Pink Sheet) | direction-filtered breakout strategy vs baseline |
| **Materials** | critical inputs (safety-stock eligible) | buffer weeks sized from the forecast band |

## The pipeline (4 layers)

```
Layer 1  Scope      Featherless (Qwen2.5-7B) + a live economic calendar     -> exposures worth forecasting
Layer 2  Forecast   FRED / Pink Sheet monthly history (+ hourly) -> Sybilion -> confidence band -> STRONG/WEAK
Layer 3  Strategy   Claude Sonnet on the strong signals (deterministic fallback) -> concrete action
Layer 4  Backtest   walk-forward vs a naive baseline on the real series         -> honest track record
```

The decision logic keys off Sybilion's `p10/p50/p90` bands: a signal is only **STRONG** when
the predicted move is large *relative to* the forecast's own uncertainty. Wide bands → don't
act (or buffer instead). The exact confidence math is in [REPORT.md](REPORT.md).

## Run

### Full demo — backend + UI, one command

A fresh clone of **just this repo** can launch the whole thing — `run_demo.sh` fetches the UI
for you. Needs **Node 18+** and `git`. From this directory:

```bash
./run_demo.sh            # mock backend (no keys/network) + UI  →  http://localhost:8080
USE_MOCK=0 ./run_demo.sh # live Sybilion backend (needs SYBILION_API_KEY) + UI
```

What it does, in order:
1. creates `.venv` and installs the Python deps (first run only);
2. starts the FastAPI agent on `:8000`;
3. finds the Lovable UI — uses a sibling `../lovable_layer` if present, otherwise **clones it**
   into `./lovable_layer` (from `LOVABLE_REPO`, gitignored), then `npm install`s it;
4. starts the UI on **`:8080`**, whose Vite dev server **proxies `/agent/* → :8000`** so the
   dashboard reaches the agent same-origin (no CORS setup).

**Ctrl-C stops both.** Overrides: `LOVABLE_DIR=/path/to/ui` to use an existing checkout,
`LOVABLE_REPO=<git url>` to clone a fork. The dashboard also runs fully on baked data if the
backend is down (it just shows a "Mock data" chip).

### Backend only

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # optional — fill in keys (see below)

uvicorn app:app --reload      # -> http://127.0.0.1:8000  (docs at /docs)
```

`USE_MOCK=1` (the default) serves realistic synthetic forecasts so the demo runs with **no
keys and no network**. `USE_MOCK=0` goes live against the real Sybilion API (needs
`SYBILION_API_KEY`). Even in mock mode, Layer 1 calls Featherless and Layer 4 pulls FRED —
both have offline fallbacks, so a clean checkout always runs.

Keys live in `.env` only (read by `config.py`): `SYBILION_API_KEY`, `FEATHERLESS_API_KEY`,
optional `ANTHROPIC_API_KEY` (Layer 3) and `TWELVEDATA_API_KEY` (hourly current month).

## HTTP API (CORS open to the Vite dev server on :5173)

| Method | Path | Returns |
|---|---|---|
| GET  | `/` | service info + enabled endpoints |
| GET  | `/scope` | Layer 1: model-picked exposures, resolved to FRED |
| GET  | `/calendar` | live economic calendar grouped by currency |
| GET  | `/signals?shock=` | every FX pair: forecast + confidence + signal (sorted) |
| GET  | `/strongest?shock=` | only high-confidence pairs + their trades |
| GET  | `/forecast/{slug}` | one pair (slug e.g. `eur_usd`) |
| GET  | `/strategy?shock=` | trades for the strongest pairs |
| GET  | `/backtest?shock=` | walk-forward P&L of the top pair's trade (real FRED) |
| GET  | `/monthly-backtest?shock=` | walk-forward over all 28 pairs, Jan→May 2026, scored vs realized |
| GET  | `/qwen-monthly?shock=` | Qwen-scoped monthly signals + monthly direction-hit track record |
| GET  | `/strategy-backtests` | per-asset (Copper, TTF gas, AT power): Sybilion-direction-filtered breakout vs naive Donchian baseline |
| POST | `/backtest/run` | Donchian breakout backtest on hourly EUR/USD, filtered by Sybilion direction |
| POST | `/safety-stock` | buffer-weeks sizing for a critical material from its forecast band (engine decides, model narrates) |
| POST | `/shock` `{ "type": "..." }` | re-run everything under a market shock |

Shock types: `boj_hike`, `ecb_cut`, `china_deval` — the "change an assumption mid-run" demo.
They re-bias the forecasts so signals and actions visibly flip (the Sunday adaptive-behavior
requirement).

## Code structure

```
run_demo.sh            one-command launcher: agent backend + the Lovable UI (../lovable_layer)
app.py                 FastAPI entrypoint — wires the layers to HTTP endpoints
config.py              the ONE config file: keys (.env), exposure universe, thresholds, horizons

# data providers (mock + real, identical shape so step2 swaps via config.USE_MOCK)
mock_sybilion.py       offline synthetic forecasts (default; powers the demo)
sybilion_client.py     real Sybilion REST client
calendar_client.py     live economic calendar (free ForexFactory/faireconomy feed)
fred_client.py         monthly FX history from FRED (keyless daily CSV -> monthly mean)
hourly_fx.py           refresh the current month's value from an hourly feed (Twelve Data)
pairs28.py             build the 28 major FX pairs as monthly series from 7 FRED USD legs

pipeline/              the decision layers
  step1_scope.py         Layer 1 — Featherless picks the exposures worth forecasting
  step2_forecast.py      Layer 2 — forecast each + score confidence (STRONG/WEAK)
  step3_strategy.py      Layer 3 — Claude Sonnet turns strong signals into actions
  step4_backtest.py      Layer 4 — walk-forward backtest vs buy-and-hold on real FRED
  monthly_backtest.py    walk-forward over all 28 pairs (Sybilion-only), scored vs realized
  qwen_monthly.py        Qwen-scoped monthly signals + monthly direction-hit track record
  donchian_backtest.py   Donchian breakout backtester for hourly EUR/USD (POST /backtest/run)
  compare_backtests.py   per-asset Sybilion-filtered strategy vs naive baseline (/strategy-backtests)
  safety_stock.py        buffer-weeks sizing from the forecast band (POST /safety-stock)

scripts/               one-off runners (NOT imported by the app) — run from repo root as
                       `python -m scripts.<name>`. These hit the REAL APIs and write to data/.
                       (live FX/commodity/power forecasts + walk-forward validation)

data/                  generated artifacts + caches (backtest JSON the frontend reads,
                       fx_cache/ and commodities/ CSVs regenerated by scripts/)
docs/
  CASE.md                the hackathon case brief (Sybilion)
  AGENT_SPEC.md          the project spec / design notes
```

## License

MIT — see [LICENSE](LICENSE).
