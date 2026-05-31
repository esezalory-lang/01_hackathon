"""
app.py — FastAPI backend for the Infineon FX Treasury Agent.

Pipeline: scope pairs (Featherless + live calendar) -> forecast (FRED+hourly ->
Sybilion, limit=0, 3m) -> rank by confidence -> strategy -> backtest.

Endpoints (JSON, CORS-enabled for the React dev server at :5173):

    GET  /scope            -> Layer 1: scoped currency pairs
    GET  /calendar         -> live economic calendar grouped by currency
    GET  /signals          -> Layer 2: every pair forecast + confidence (sorted)
    GET  /strongest        -> only the highest-confidence pairs + their trades
    GET  /forecast/{pair}  -> one pair's forecast (slug, e.g. eur_usd)
    GET  /strategy         -> trades for the strongest pairs
    GET  /backtest         -> walk-forward P&L of the top pair's trade
    POST /backtest/run     -> Donchian breakout backtest on hourly EUR/USD (Sybilion-direction filtered)
    POST /shock            -> re-run under a shock; returns everything the UI needs

USE_MOCK (config) toggles mock vs live Sybilion/FRED. Frontend builds on mock.
"""
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
import mock_sybilion
from calendar_client import high_impact_by_currency
from pipeline.step1_scope import scope_pairs
from pipeline.step2_forecast import run as run_forecasts, select_strongest
from pipeline.step3_strategy import recommend_strategy
from pipeline.step4_backtest import run as run_backtest
from pipeline.monthly_backtest import run_monthly_backtest
from pipeline.qwen_monthly import run_qwen_monthly
from pipeline.safety_stock import decide_and_narrate, is_material, MATERIALS
from pipeline.compare_backtests import run as run_strategy_backtests
# NOTE: donchian_backtest (pandas/numpy) and yfinance are imported lazily inside
# /backtest/run so the rest of the API still works if those heavy deps are absent.

app = FastAPI(title="Infineon FX Treasury Agent", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _pair_meta_for(slug):
    pair = config.SLUG_TO_PAIR.get(slug)
    if not pair:
        return None
    meta = config.PAIR_UNIVERSE[pair]
    return {"pair": pair, "slug": slug, "fred_id": meta["fred_id"], "quote": meta["quote"]}


def _top_trade(strong, trades):
    """Match the highest-confidence pair to its trade for the backtest."""
    if not strong:
        return {}, None
    top = strong[0]
    for t in trades:
        if t.get("pair") == top["pair"]:
            return t, _pair_meta_for(top["slug"])
    return {"pair": top["pair"], "action": f"{'SELL' if top['direction']=='DOWN' else 'BUY'} forward"}, \
        _pair_meta_for(top["slug"])


@app.get("/")
def root():
    return {
        "service": "Infineon FX Treasury Agent",
        "use_mock": config.USE_MOCK,
        "horizon_months": config.SOFT_HORIZON,
        "confidence_threshold": config.CONFIDENCE_THRESHOLD,
        "shock_types": mock_sybilion.SHOCK_TYPES,
        "endpoints": ["/monthly-backtest", "/qwen-monthly", "/scope", "/calendar",
                      "/signals", "/strongest", "/forecast/{pair}", "/strategy",
                      "/backtest", "/backtest/run", "/shock"],
    }


@app.get("/monthly-backtest")
def monthly_backtest(shock: str | None = None):
    """Walk-forward: for each 2026 month, send all 28 pairs to Sybilion, pick 6
    (3 buy + 3 sell) and surface the strongest BUY and strongest SELL, scored
    against the realized value. Writes data/monthly_backtest.json for the partner."""
    return run_monthly_backtest(shock=shock)


@app.get("/qwen-monthly")
def qwen_monthly(shock: str | None = None, refresh: bool = False):
    """Qwen-scoped monthly signals: Qwen picks Infineon's operations-relevant
    pairs, their monthly FRED series is cached, and a Sybilion 1-month walk-forward
    runs Jan-2026→now. Returns the STRONG buys/sells per month (with realized value
    + direction hit) for self-backtesting. Writes data/qwen_monthly_signals.json."""
    return run_qwen_monthly(shock=shock, refresh=refresh)


@app.get("/scope")
def scope():
    return {"pairs": scope_pairs()}


@app.get("/calendar")
def calendar():
    return {"by_currency": high_impact_by_currency()}


@app.get("/signals")
def signals(shock: str | None = None):
    results = run_forecasts(shock=shock)
    select_strongest(results)  # tags `selected`
    return {"shock": shock, "signals": results}


@app.get("/strongest")
def strongest(shock: str | None = None):
    results = run_forecasts(shock=shock)
    strong = select_strongest(results)
    return {"shock": shock, "strongest": strong, "trades": recommend_strategy(strong)}


@app.get("/forecast/{pair}")
def forecast(pair: str, shock: str | None = None):
    if pair not in config.SLUG_TO_PAIR:
        raise HTTPException(status_code=404, detail=f"unknown pair '{pair}'")
    for r in run_forecasts(shock=shock):
        if r["slug"] == pair:
            return r
    raise HTTPException(status_code=404, detail=f"no forecast for '{pair}'")


@app.get("/strategy")
def strategy(shock: str | None = None):
    strong = select_strongest(run_forecasts(shock=shock))
    return {"shock": shock, "trades": recommend_strategy(strong)}


@app.get("/backtest")
def backtest(shock: str | None = None):
    results = run_forecasts(shock=shock)
    strong = select_strongest(results)
    trades = recommend_strategy(strong)
    trade, pair_meta = _top_trade(strong, trades)
    return run_backtest(trade, pair_meta=pair_meta)


@app.post("/backtest/run")
def backtest_endpoint(payload: dict):
    """
    payload = {
      "asset": "EURUSD",                # only EURUSD for now
      "direction": "SELL" | "BUY" | "BOTH",  # from Sybilion recommendation
      "months_back": 6
    }
    Fetches hourly EUR/USD for the period, runs the Donchian breakout backtest
    filtered by direction, returns the trades + equity curve + stats.
    """
    import yfinance as yf
    from pipeline.donchian_backtest import run_backtest as run_donchian_backtest, compute_indicators

    months_back = payload.get("months_back", 6)
    direction = payload.get("direction", "SELL").upper()

    end = datetime.now()
    start = end - timedelta(days=months_back * 31)

    # Yahoo Finance: EURUSD=X, hourly bars
    ticker = yf.Ticker("EURUSD=X")
    df = ticker.history(start=start, end=end, interval="1h")
    if df.empty:
        raise HTTPException(status_code=502, detail="Could not fetch EUR/USD data")

    df = df.reset_index().rename(columns={
        "Datetime": "date", "Date": "date",
        "High": "high", "Low": "low", "Close": "close", "Open": "open",
    })
    df["date"] = df["date"].astype(str)

    result = run_donchian_backtest(df, direction_filter=direction)

    # Price series for the frontend to overlay trades on. Build it from the SAME
    # post-warmup frame the backtest walks (compute_indicators+dropna+reset_index)
    # so trade entry_idx/exit_idx align with these indices.
    frame = compute_indicators(df).dropna().reset_index(drop=True)
    result["price_series"] = [
        {"date": str(r.get("date", i)), "price": float(r["close"]), "idx": i}
        for i, r in frame.iterrows()
    ]
    return result


@app.get("/strategy-backtests")
def strategy_backtests():
    """Per-asset dual backtest: hardcoded Donchian (monthly) vs the Sybilion
    forecast-driven backtest, on the real monthly series. Writes
    data/strategy_backtests.json. No network — safe to call anytime."""
    return run_strategy_backtests()


@app.post("/safety-stock")
def safety_stock(payload: dict):
    """Safety-stock sizing from the forecast band (engine decides, Qwen narrates).

    payload = {asset, current_price, band_width, direction: "UP"|"DOWN", confidence?}
    Wider band -> more buffer weeks; upward bias -> pre-buy, downward -> run lean.
    Only critical materials (see MATERIALS) are bufferable.
    """
    asset = payload.get("asset", "")
    if not is_material(asset):
        raise HTTPException(status_code=400,
                            detail=f"'{asset}' is not a bufferable material. valid: {list(MATERIALS)}")
    try:
        return decide_and_narrate(
            asset,
            current_price=float(payload["current_price"]),
            band_width=float(payload["band_width"]),
            direction=str(payload.get("direction", "UP")).upper(),
            confidence=payload.get("confidence"),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"bad payload: {e}")


class ShockRequest(BaseModel):
    type: str | None = None


@app.post("/shock")
def shock(req: ShockRequest):
    if req.type and req.type not in mock_sybilion.SHOCK_TYPES:
        raise HTTPException(status_code=400,
                            detail=f"unknown shock '{req.type}'. valid: {mock_sybilion.SHOCK_TYPES}")
    results = run_forecasts(shock=req.type)
    strong = select_strongest(results)
    trades = recommend_strategy(strong)
    trade, pair_meta = _top_trade(strong, trades)
    return {
        "shock": req.type,
        "signals": results,
        "strongest": strong,
        "trades": trades,
        "backtest": run_backtest(trade, pair_meta=pair_meta),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
