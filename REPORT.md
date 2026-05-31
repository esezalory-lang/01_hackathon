# REPORT — Infineon FX Treasury Agent

**Team 43 Food** — Elliot Sezalory, Fridolin Sitter · Sybilion Hackathon 2026

## TL;DR

We built a decision agent on top of the **Sybilion** probabilistic forecasting API that
plays FX treasury for a power-semiconductor maker (Infineon): it scopes which currency
pairs matter, forecasts them, keeps only the high-confidence signals, turns those into
concrete hedge trades, and **walk-forward backtests every recommendation on real FRED
data** so nothing is taken on faith. The forecasting model is an API — our value is the
confidence scoring and the honest validation layered on top.

## Problem

A semiconductor manufacturer pays suppliers and books revenue across many currencies, so
unhedged FX moves hit margin directly. The treasury question is not "what will EUR/USD do"
but **which exposures are worth acting on, with what conviction, and would acting on them
actually have made money.** A raw forecast doesn't answer that — a point estimate with no
uncertainty and no track record is not decision-grade. We decided to solve the layer
*between* a forecast API and a trade: turn probabilistic forecasts into ranked, confidence-
scored, backtested hedge recommendations.

## Approach

- **4-layer pipeline.** Layer 1 (Scope) uses Featherless `Qwen2.5-7B-Instruct` + a live
  economic calendar to pick the pairs worth forecasting. Layer 2 (Forecast) builds monthly
  FRED histories and submits them to Sybilion. Layer 3 (Strategy) turns strong signals into
  trades with Claude Sonnet (deterministic fallback if no key). Layer 4 (Backtest) runs a
  walk-forward vs buy-and-hold on the pair's real FRED series.
- **Confidence score is the core idea.** We collapse Sybilion's `p10/p50/p90` bands into a
  single 0–100 conviction: `conviction = price_move / band_width`, then
  `confidence = 100·tanh(conviction)·(1 − min(mape,50)/50)`. A forecast only becomes a
  STRONG signal when the directional move is large *relative to* the forecast's own
  uncertainty — this is what filters noise from signal.
- **Walk-forward, not in-sample.** Backtests truncate history and score each forecast
  against the *realized* next value, so reported accuracy is out-of-sample.
- **Mock-first architecture.** `mock_sybilion.py` and `sybilion_client.py` share an
  identical response shape, so the whole app runs offline (`USE_MOCK=1`) for the demo and
  swaps to live Sybilion via one config flag — Layer 1 (Featherless) and Layer 4 (FRED)
  both have offline fallbacks too, so a clean checkout always runs with zero keys.
- **Shock scenarios.** `boj_hike`, `ecb_cut`, `china_deval` re-bias the forecasts mid-run
  so signals and trades visibly flip — the "change an assumption and re-decide" demo.

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

Runs with **no keys and no network** by default (`USE_MOCK=1` serves realistic synthetic
forecasts; Layer 1 and Layer 4 fall back offline). To go live against the real Sybilion API
set `USE_MOCK=0` and fill `SYBILION_API_KEY` in `.env`. Optional keys: `FEATHERLESS_API_KEY`
(Layer 1 model scoping), `ANTHROPIC_API_KEY` (Layer 3 trades), `TWELVEDATA_API_KEY` (hourly
current-month refresh). Keys are read only from `.env` by `config.py` — none are committed.

Key endpoints: `/signals` (all pairs scored), `/strongest` (high-confidence + trades),
`/backtest` (walk-forward P&L of the top trade), `/monthly-backtest` (28 pairs, Jan→May
2026 scored vs realized), `POST /shock` (re-run under a market shock). Full table in
[README.md](README.md).

The `scripts/` runners (`python -m scripts.<name>`) hit the **real** APIs and regenerate the
artifacts in `data/` — they are not needed to run the app.

## Results

| Backtest | Window | Signals | Direction hit |
|---|---|---|---|
| Monthly, mock forecasts | 2026-05 | 6 | **83%** (STRONG-only: 2/2) |
| Monthly, **live Sybilion** | 2026-01 → 2026-05 | 30 | **40%** |

The headline is the *gap* between the two, and we report it openly: the mock demo looks
strong, but the live 5-month walk-forward across all 28 pairs lands at 40% direction-hit —
roughly coin-flip at the monthly horizon. The confidence filter helps (STRONG signals beat
WEAK ones in the mock set), but a univariate monthly forecast is a weak directional edge on
real data, and our backtests say so. Per-asset strategy backtests (Copper, TTF Gas, AT
Power) compare a Sybilion-direction-filtered Donchian breakout against an unfiltered
baseline; artifacts: `data/monthly_backtest_live.json`, `data/strategy_backtests.json`,
`data/pairs28_h6_live.json`.

## What worked / What didn't

**Worked**
- The confidence score genuinely separated conviction from noise — STRONG signals
  out-hit WEAK ones, and it gave the UI a single number to rank on.
- Mock-first design: identical mock/live response shapes meant a clean checkout runs with
  zero keys, and the live swap was a one-flag change — huge for demoing.
- Walk-forward backtesting kept us honest and caught over-optimistic reads early.

**Didn't / caveats**
- Monthly univariate forecasts are a thin directional edge — 40% live direction-hit.
- Sybilion needs ≥40 monthly points (60+ for 6-month horizon), so histories must start in
  2022–2023 to keep truncated walk-forward windows valid; this limits how far back we test.
- We submit with `filters.limit = 0` (pure univariate, no external drivers) — leaving
  commodity cost-drivers on the table.
- A SELL EUR/USD shows negative P&L because EUR rallied into 2026 — reported as-is, not
  cherry-picked.

## What we'd do with another 36 hours

- **Feed cost-drivers into the forecast** (`filters.limit > 0`): copper, TTF gas, power —
  the commodity series are already fetched in `scripts/commodities_*`. Multivariate forecasts
  are the most likely path to beat 40%.
- **Position sizing from confidence**, not just go/no-go — scale hedge notional by score.
- **Calibration report**: are 70%-confidence signals right 70% of the time? Reliability
  curves over the full live history.
- **Lengthen the live track record** beyond 5 months and add transaction costs to the P&L.

## Credits & dependencies

- **Forecasting:** Sybilion Ops API (probabilistic monthly forecasts).
- **Models:** Featherless `Qwen/Qwen2.5-7B-Instruct` (Layer 1 scoping), Anthropic Claude
  Sonnet (Layer 3 strategy, optional).
- **Data:** FRED (monthly FX history, keyless daily CSV → monthly mean), Twelve Data
  (hourly current-month refresh), World Bank Pink Sheet (commodity cost-drivers),
  ForexFactory/faireconomy (economic calendar).
- **Libraries:** FastAPI, Uvicorn, requests, python-dotenv, anthropic, openai, pandas,
  openpyxl, yfinance.
- **AI coding tools:** Claude Code (Anthropic) was used during development.
