# REPORT — Infineon Cost & Treasury Agent

**Team 43 Food** — Elliot Sezalory, Fridolin Sitter · Sybilion Hackathon 2026 (Forecasting AI track)

## TL;DR

We built a decision agent on top of the **Sybilion** probabilistic forecasting API that
manages cost & treasury for a European power-semiconductor maker (Infineon). Its inputs
price in USD while it reports in EUR, so the agent scopes the exposures that move
margin — **FX, wholesale power, and commodity cost-drivers** — forecasts each through
Sybilion, keeps only the high-confidence signals, and turns them into concrete actions (FX
hedge, power hedge, or safety-stock buffer), **walk-forward backtested on real data**. The
forecast is an API; our value is the confidence scoring, the per-exposure decision rules, and
the honest validation on top.

## Problem

A semiconductor manufacturer is exposed on several fronts at once: USD-denominated supplier
payments (FX), energy-intensive fabs (wholesale power), and metal/material inputs (copper,
gallium, gas). A point forecast doesn't answer the treasury question, which is **which of
these exposures is worth acting on, with what conviction, what action, and would acting on it
historically have helped.** We deliberately did *not* scope to a single series — the interesting
problem is multi-exposure: the same Sybilion bands have to drive three different decision types
(hedge a currency, hedge power, or buffer a material), and the agent has to decide *which* and
*when* — including when the right answer is "bands too wide, don't act."

## Approach

- **Multi-exposure, 4-layer pipeline.** Layer 1 (Scope) uses Featherless `Qwen2.5-7B-Instruct`
  + a live economic calendar to pick the exposures worth forecasting. Layer 2 (Forecast) builds
  monthly histories (FRED for FX, World Bank Pink Sheet for commodities, Ember/APG for AT power)
  and submits them to Sybilion. Layer 3 (Strategy) maps strong signals to an action per exposure
  type (FX forward, power hedge, safety-stock buffer) with Claude Sonnet, deterministic fallback.
  Layer 4 (Backtest) walk-forwards each recommendation against the realized series.
- **One confidence score, three decisions.** We collapse Sybilion's `p10/p50/p90` into a 0–100
  conviction and reuse it across exposures: `conviction = price_move / band_width`, then
  `confidence = 100·tanh(conviction)·(1 − min(mape,50)/50)`. A signal is **STRONG** only when the
  predicted move is large *relative to* the forecast's own uncertainty. The band width also drives
  **safety-stock sizing** — wide bands → more buffer weeks, directional bias → pre-buy vs run lean.
- **Direction-filtered strategies, not raw forecasts.** For commodities/power we don't trade the
  forecast directly; we use the Sybilion direction as a *filter* on a Donchian breakout strategy,
  then backtest filtered vs unfiltered to measure what the forecast actually adds.
- **Walk-forward, not in-sample.** Every backtest truncates history and scores against the
  *realized* next value, so accuracy is out-of-sample.
- **Mock-first architecture.** `mock_sybilion.py` and `sybilion_client.py` share an identical
  shape, so the whole app runs offline (`USE_MOCK=1`) and swaps to live Sybilion via one flag;
  Layer 1 and Layer 4 have offline fallbacks too, so a clean checkout always runs with zero keys.
- **Shock scenarios.** `boj_hike`, `ecb_cut`, `china_deval` re-bias the forecasts mid-run so
  signals and actions visibly flip — the Sunday adaptive-behavior requirement.

The confidence math, in full:

```
band_width = (p90 - p10) / p50            # relative forecast uncertainty
price_move = |p50 - current| / current    # directional magnitude
conviction = price_move / band_width
confidence = 100 * tanh(conviction) * (1 - min(mape, 50)/50)   # 0-100
signal     = STRONG if confidence >= threshold else WEAK
```

## How to run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # optional — see below

uvicorn app:app --reload        # -> http://127.0.0.1:8000  (interactive docs at /docs)
```

Runs with **no keys and no network** by default (`USE_MOCK=1`; Layer 1 and Layer 4 fall back
offline). For live forecasts set `USE_MOCK=0` and fill `SYBILION_API_KEY`. Optional keys:
`FEATHERLESS_API_KEY` (Layer 1), `ANTHROPIC_API_KEY` (Layer 3), `TWELVEDATA_API_KEY` (hourly
current month). Keys are read only from `.env` by `config.py` — none are committed.

Endpoints span all exposures: `/signals` & `/strongest` (FX), `/strategy-backtests` (commodities
& power: filtered vs baseline), `/safety-stock` (materials), `/monthly-backtest` (28 FX pairs
scored vs realized), `POST /shock` (re-run under a market shock). Full table in
[README.md](README.md). The `scripts/` runners hit the **real** APIs and regenerate the `data/`
artifacts; they are not needed to run the app.

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

The honest read: the Sybilion direction filter **consistently cuts trade count and drawdown**,
and on AT power it flips a losing strategy positive — but **none of these beat naive buy-and-hold**
over the long windows (copper B&H +154%, power +254%). That's an unfair bar for a hedger: "buy and
hold a cost input forever" isn't a treasury action — the meaningful comparison is filtered vs
unfiltered, where the forecast clearly helps. Direction skill is real but uneven: ~60% next-month
on gas and power, only 20% on copper, and 40% across the live FX set — roughly coin-flip at the
monthly horizon for currencies. We report the gap between the polished mock demo (83%) and live
reality (40%) openly. Artifacts: `data/monthly_backtest_live.json`, `data/strategy_backtests.json`,
`data/commodities_forecast.json`, `data/at_power_h6.json`, `data/pairs28_h6_live.json`.

## What worked / What didn't

**Worked**
- One confidence score generalized across three exposure types and gave the UI a single number
  to rank on; STRONG beat WEAK in the mock set.
- Using the forecast as a **direction filter** on a breakout strategy was the clearest win —
  it cut drawdown on every asset and turned AT power from −0.4% to +0.3%.
- Band-width-driven **safety-stock sizing** uses the uncertainty directly instead of hiding it.
- Mock-first design: identical mock/live shapes meant zero-key clean-checkout runs and a one-flag
  live swap — huge for demoing and for the mid-run shock scenarios.

**Didn't / caveats**
- Monthly univariate forecasts are a thin directional edge: 40% live FX direction-hit, 20% on copper.
- Nothing beats long-window buy-and-hold (expected for trending cost inputs; not the right baseline).
- Sybilion needs ≥40 monthly points (60+ for 6-month, 120 for 12), so histories must start in
  2013–2023 to keep truncated walk-forward windows valid.
- We submit with `filters.limit = 0` (pure univariate, **no external driver signals**) — leaving
  Sybilion's driver-importance output, the most decision-relevant part, on the table.

## What we'd do with another 36 hours

- **Turn on external drivers** (`filters.limit > 0`) and surface Sybilion's driver-importance per
  horizon — directly addresses the jury's "visible reasoning" dimension and is the most likely path
  to beat 40%. Copper ← China export controls; power ← gas + carbon; FX ← rate differentials.
- **Cross-exposure synthesis:** a USD spike raises *both* FX hedge need and material cost — let the
  agent reason across exposures instead of one at a time.
- **Confidence-scaled sizing** (hedge ratio / buffer weeks proportional to score) and a calibration
  report: are 70%-confidence signals right 70% of the time?
- **Longer live track record** beyond 5 months, with transaction costs in the P&L.

## Credits & dependencies

- **Forecasting:** Sybilion Ops API (probabilistic monthly forecasts + backtest accuracy).
- **Models:** Featherless `Qwen/Qwen2.5-7B-Instruct` (Layer 1 scoping), Anthropic Claude Sonnet
  (Layer 3 strategy / narration, optional).
- **Data:** FRED (FX history), World Bank Pink Sheet (copper, TTF gas, gold), Ember/APG (Austria
  day-ahead power), Twelve Data (hourly current month), ForexFactory/faireconomy (economic calendar).
- **Libraries:** FastAPI, Uvicorn, requests, python-dotenv, anthropic, openai, pandas, openpyxl, yfinance.
- **AI coding tools:** Claude Code (Anthropic) was used during development.
