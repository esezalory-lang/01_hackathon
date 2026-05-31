# Team 43 Food — Forecasting AI (Sybilion)

## Team

- **Elliot Sezalory**
- **Fridolin Sitter**

**Track:** Forecasting AI (Sybilion)

---

## TL;DR

We built a **decision agent on top of the Sybilion probabilistic forecasting API** that plays
cost & treasury for a European power-semiconductor maker (Infineon). It scopes the exposures
that move margin — **FX, wholesale power, and commodities** — forecasts each through Sybilion,
keeps only the high-confidence signals, and turns them into concrete actions (FX hedge, power
production-scheduling, or safety-stock buffer), **walk-forward backtested on real data**. The
forecast is the API; our contribution is the confidence scoring, the per-exposure decision
rules, the honest validation, and a live dashboard.

---

## Problem

A semiconductor manufacturer is exposed on several fronts at once: USD-denominated supplier
payments (**FX**, since it reports in EUR), energy-intensive fabs (**wholesale power**), and
metal/material inputs (**copper, gallium, gas**). A point forecast doesn't answer the treasury
question, which is: **which of these exposures is worth acting on, with what conviction, what
action, and would acting on it historically have helped?**

We deliberately did **not** scope to a single series. The interesting problem is multi-exposure:
the same Sybilion `p10/p50/p90` bands must drive three *different* decision types — hedge a
currency, schedule energy-intensive production, or buffer a material — and the agent has to
decide *which* and *when*, including when the right answer is **"bands too wide, don't act."**
We borrow the industrial framing (power-cost-aware scheduling) but keep the engine a forecasting
decision agent — we did not attempt the Infineon process-sequence track task.

---

## Approach

- **Multi-exposure, 4-layer pipeline.** Layer 1 (Scope) — Featherless `Qwen2.5-7B-Instruct` + a
  live economic calendar pick the exposures worth forecasting. Layer 2 (Forecast) — build monthly
  histories (FRED for FX, World Bank Pink Sheet for commodities, Ember/APG for AT power) and submit
  to Sybilion. Layer 3 (Strategy) — map strong signals to a per-exposure action (FX forward, power
  schedule, safety-stock buffer), with Claude Sonnet narration and a deterministic fallback. Layer 4
  (Backtest) — walk-forward each recommendation against the realized series.
- **One confidence score, three decisions.** Collapse the bands into a 0–100 conviction and reuse
  it everywhere: `conviction = price_move / band_width`, `confidence = 100·tanh(conviction)·(1 −
  min(mape,50)/50)`. A signal is **STRONG** only when the move is large *relative to* its own
  uncertainty. Band width also drives **safety-stock sizing** (wider band → more buffer weeks).
- **Forecast as a filter, not a trade.** For commodities/power we use the Sybilion *direction* to
  filter a Donchian breakout strategy, then backtest filtered vs unfiltered to isolate what the
  forecast adds. EUR/USD additionally runs a real hourly Donchian backtest.
- **Walk-forward, not in-sample.** Every backtest truncates history and scores against the realized
  next value — accuracy is out-of-sample.
- **Mock-first + shock engine.** `mock_sybilion.py` and `sybilion_client.py` share one shape, so the
  app runs offline (`USE_MOCK=1`) and swaps to live with one flag. Shocks (`boj_hike`, `ecb_cut`,
  `china_deval`) re-bias forecasts mid-run so signals/actions visibly flip — the Sunday adaptive
  requirement.

```
band_width = (p90 - p10) / p50            # relative forecast uncertainty
price_move = |p50 - current| / current    # directional magnitude
conviction = price_move / band_width
confidence = 100 * tanh(conviction) * (1 - min(mape, 50)/50)   # 0-100
signal     = STRONG if confidence >= threshold else WEAK
```

The system runs **locally**: a FastAPI backend (this repo) + a Vite/React dashboard
(`lovable_layer`), calling the Sybilion, Featherless, FRED and (optional) Anthropic/Twelve Data APIs.

---

## How to run it

A fresh clone of **just this repo** launches the whole thing — the script fetches the UI for you
(needs **Node 18+** and `git`):

```bash
git clone https://github.com/esezalory-lang/01_hackathon.git
cd 01_hackathon
./run_demo.sh                # mock backend + Lovable UI  →  http://localhost:8080
USE_MOCK=0 ./run_demo.sh     # live Sybilion (needs SYBILION_API_KEY) + UI
```

`run_demo.sh` creates the `.venv`, starts the FastAPI agent on `:8000`, then finds the Lovable UI
(sibling `../lovable_layer` if present, else **clones** it from `LOVABLE_REPO`) and starts it on
`:8080`, with Vite proxying `/agent/* → :8000`. **Ctrl-C stops both.**

**Backend only:** `python3 -m venv .venv && source .venv/bin/activate && pip install -r
requirements.txt && uvicorn app:app --reload` (→ `http://127.0.0.1:8000`, docs at `/docs`).

Runs with **no keys and no network** by default (`USE_MOCK=1`; Layers 1 & 4 fall back offline).
Keys are read only from `.env` by `config.py`: `SYBILION_API_KEY` (live forecasts),
`FEATHERLESS_API_KEY` (Layer 1), optional `ANTHROPIC_API_KEY` (Layer 3) and `TWELVEDATA_API_KEY`.
Full endpoint table and code structure in **[README.md](README.md)**.

---

## Results

**FX — monthly direction-hit (walk-forward, scored vs realized):**

| Backtest | Window | Signals | Direction hit |
|---|---|---|---|
| Mock forecasts | 2026-05 | 6 | 83% (STRONG-only 2/2) |
| **Live Sybilion** | 2026-01 → 2026-05 | 30 | **40%** |

**Commodities & power — Sybilion direction filter vs unfiltered Donchian baseline**
(per-asset, real monthly series, `data/strategy_backtests.json`):

| Asset | Forecast | Baseline (both dirs) | + Sybilion filter | Next-month dir. hit |
|---|---|---|---|---|
| Copper (132m) | DOWN | 10 trades, +0.9% | 8 trades, −0.0%, **½ the drawdown** | 20% |
| TTF gas (132m) | UP | 11 trades, **−2.5%** | 4 trades, **−0.2%** (cut the losers) | 60% |
| AT power (137m) | UP | 10 trades, −0.4% | 3 trades, **+0.3%** (filter flipped it positive) | 60% |

**Baseline comparison:** the Sybilion direction filter **consistently cuts trade count and
drawdown**, and on AT power flips a losing strategy positive. **None beat long-window
buy-and-hold** (copper B&H +154%, power +254%) — but "buy and hold a cost input forever" is not a
treasury action; the meaningful baseline is *filtered vs unfiltered*, where the forecast clearly
helps. Direction skill is real but uneven (~60% next-month on gas/power, 20% copper, 40% live FX).
We report the gap between the polished mock demo (83%) and live reality (40%) openly.

**Raw outputs:** `data/monthly_backtest_live.json`, `data/strategy_backtests.json`,
`data/commodities_forecast.json`, `data/at_power_h6.json`, `data/pairs28_h6_live.json`,
`data/eur_usd_h6.json`.

---

## What worked

- **One confidence score across three exposure types** gave the UI a single number to rank on, and
  cleanly separated "act" from "monitor / buffer instead."
- **Forecast-as-a-filter** was the clearest win: it cut drawdown on every commodity/power asset and
  turned AT power from −0.4% to +0.3% — an apples-to-apples measure of the forecast's value.
- **Band-width → safety-stock / production-scheduling** uses the uncertainty *directly* (wide band =
  more buffer; rising power forecast = run energy-intensive steps now), instead of hiding it.
- **Mock-first design**: identical mock/live shapes → zero-key clean-checkout runs, one-flag live
  swap, and instant mid-run shock scenarios.

---

## What didn't work

- **Monthly univariate forecasts are a thin directional edge** — 40% live FX direction-hit, 20% on
  copper (roughly coin-flip at the monthly horizon for currencies).
- **Nothing beats long-window buy-and-hold** for trending cost inputs (expected; not the right
  baseline, but worth stating plainly).
- **We ran Sybilion with `filters.limit = 0`** (pure univariate, no external driver datasets),
  leaving its **driver-importance output — the most decision-relevant part — on the table.**
- **History-length constraints**: Sybilion needs ≥40 monthly points (60+ for 6-month, 120 for 12),
  so series must start in 2013–2023 to keep truncated walk-forward windows valid.

---

## What you'd do with another 36 hours

- **Turn on external drivers** (`filters.limit > 0`) and surface Sybilion's driver-importance per
  horizon (copper ← China export controls; power ← gas + carbon; FX ← rate differentials) — the most
  likely path past 40% and directly addresses "visible reasoning."
- **Cross-exposure synthesis:** a USD spike raises *both* FX-hedge need and material cost — let the
  agent reason across exposures instead of one at a time.
- **Confidence-scaled sizing** (hedge ratio / buffer weeks ∝ score) plus a **calibration report**:
  are 70%-confidence signals right 70% of the time?
- **Longer live track record** beyond 5 months, with transaction costs in the P&L.

---

## Track-specific deliverables

### 📈 Forecasting AI (Sybilion)
- [x] **Working agent or application — not slideware** — FastAPI agent + live React dashboard
  (`./run_demo.sh`), runs against live Sybilion or fully offline.
- [x] **Backtest results validating the decision logic** — walk-forward FX (`/monthly-backtest`),
  per-asset filtered-vs-baseline (`/strategy-backtests`), hourly EUR/USD Donchian (`/backtest/run`).
- [x] **Driver-importance visualization in the demo** — the dashboard has a Driver-Importance panel.
  ⚠️ **It is illustrative, not live Sybilion driver output** (we submitted with `filters.limit=0`);
  see the honesty note.
- [x] **Adapts to a mid-run assumption shift on Sunday** — `POST /shock` (`boj_hike`, `ecb_cut`,
  `china_deval`) re-biases forecasts so signals and actions visibly flip mid-run.
- [x] **Domain choice rationale** — stated under **Problem** (multi-exposure cost & treasury).

---

## Credits & dependencies

- **Open-source libraries:** FastAPI, Uvicorn, requests, python-dotenv, pandas, openpyxl,
  yfinance (≥0.2.40), anthropic, openai (Python); React 19, Vite, TanStack Start/Router, Recharts 3,
  shadcn/ui, Tailwind, embla-carousel (frontend).
- **Pre-trained models:** Featherless `Qwen/Qwen2.5-7B-Instruct` (Layer 1 scoping + action
  narration); Anthropic Claude Sonnet (Layer 3 strategy, optional — deterministic fallback otherwise).
- **External APIs:** Sybilion Ops API (probabilistic forecasts); FRED (FX history); Featherless
  (Qwen); Anthropic (Claude, optional); Twelve Data (hourly current month, optional);
  ForexFactory/faireconomy (economic calendar); Yahoo Finance via yfinance (hourly EUR/USD backtest).
- **Datasets:** FRED FX series; World Bank Pink Sheet (copper, TTF gas, gold); Ember/APG (Austria
  day-ahead power). Public sources used under their respective terms.
- **AI coding assistants:** Claude Code (Anthropic) was used during the hackathon.

---

## A note on honesty

What is real vs. mocked/curated, stated plainly:

- **Real:** all Sybilion forecasts used for EUR/USD, AT power, copper and TTF gas (live `h6` runs,
  84–137-month windows); FRED histories; the hourly EUR/USD Donchian backtest (real Yahoo data); the
  walk-forward direction-hit numbers in Results. The confidence scoring, decision rules, and
  backtests are genuine and out-of-sample.
- **Illustrative / mocked:**
  - The **Driver-Importance panel is illustrative** — we ran with `filters.limit=0`, so it is not
    live Sybilion driver output.
  - **Gallium and the SCFI shipping index** in the dashboard use synthetic forecasts (no real series
    sourced); the other four assets are real.
  - **Operational constants are placeholders** — safety-stock weekly usage / lead times, and the
    power "≈4,000 MWh batch" energy load. The *forecast* inputs (bands, direction, prices) are real;
    these ops parameters are reasonable stand-ins a real deployment would calibrate.
  - The **Qwen power-scheduling sentence was lightly curated** when the live model returned a terse
    line; the numbers it states are engine-decided, not model-invented.
  - The dashboard ships some data **baked from real backend artifacts** so the UI demos offline; it
    upgrades to live values when the agent backend is running.
- **`USE_MOCK=1` (default)** serves realistic synthetic forecasts so a clean checkout runs with no
  keys/network; `USE_MOCK=0` is the live path the Results numbers come from.

---

*Submitted by team Team 43 Food for Zero One Hack_01, 2026-05-31.*
