# FX Treasury Agent — Backend

Procurement/treasury FX agent for Infineon. Pipeline:

```
Layer 1  scope pairs      Featherless (Qwen2.5-7B) + live economic calendar  -> currency pairs
Layer 2  forecast + rank  FRED monthly (2023->now) + hourly current month -> Sybilion -> confidence
Layer 3  strategy         Claude Sonnet on the strongest pairs (deterministic fallback)
Layer 4  backtest         walk-forward vs buy-and-hold on the pair's real FRED series
```

## Run

```bash
pip install -r requirements.txt
cp .env.example .env          # fill in keys
uvicorn app:app --reload      # http://127.0.0.1:8000
```

`USE_MOCK=1` (default) serves canned forecasts so the frontend can build immediately.
`USE_MOCK=0 uvicorn app:app` goes live (needs SYBILION_API_KEY).

Note: even in mock mode, Layer 1 (scope) calls Featherless and Layer 4 (backtest)
pulls FRED — both have offline fallbacks, so it still runs without network/keys.

## Endpoints (CORS open to http://localhost:5173)

| Method | Path | Returns |
|---|---|---|
| GET | `/scope` | Layer-1 currency pairs (model-picked, resolved to FRED) |
| GET | `/calendar` | live economic calendar grouped by currency |
| GET | `/signals?shock=` | every pair: forecast + confidence + signal + selected (sorted) |
| GET | `/strongest?shock=` | only high-confidence pairs + their trades |
| GET | `/forecast/{slug}` | one pair (slug e.g. `eur_usd`) |
| GET | `/strategy?shock=` | trades for the strongest pairs |
| GET | `/backtest?shock=` | walk-forward P&L of the top pair's trade (real FRED) |
| POST | `/shock` `{ "type": "..." }` | re-run under a shock; signals+strongest+trades+backtest |

Shock types: `boj_hike`, `ecb_cut`, `china_deval`. (`china_deval` flips USD/CNY WEAK→STRONG.)

## Confidence (Layer 2)

```
band_width = (p90 - p10) / p50           # relative uncertainty at the 3m horizon
price_move = |p50 - current| / current   # directional magnitude
conviction = price_move / band_width
confidence = 100 * tanh(conviction) * (1 - min(mape,50)/50)   # 0-100
signal     = STRONG if confidence >= 50 else WEAK
```

## Decisions / caveats

- **Model:** the spec asked for `meta-llama/Llama-4-Scout-17B-16E-Instruct`, but Featherless
  hosts no Llama-4, and its Llama-3.x are gated. Default is the open, non-gated
  `Qwen/Qwen2.5-7B-Instruct`. Override with `FEATHERLESS_MODEL` in `.env`.
- **Calendar:** Myfxbook has no clean free API; we use the free ForexFactory/faireconomy
  JSON feed as the calendar source ([calendar_client.py](calendar_client.py)).
- **History start = 2023** -> ~41 monthly points -> Sybilion 3-month horizon (60+ pts
  needed for 6m). Set in `config.SOFT_HORIZON`.
- **Hourly current month:** uses Twelve Data when `TWELVEDATA_API_KEY` is set, else
  averages the current month's FRED dailies.
- **`filters.limit = 0`** on Sybilion submit -> no external driver datasets (pure univariate).
- Backtests use **real FRED data** and are reported honestly — e.g. SELL EUR/USD is
  currently negative because EUR rallied into 2026.
```
