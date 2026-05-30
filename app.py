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
    POST /shock            -> re-run under a shock; returns everything the UI needs

USE_MOCK (config) toggles mock vs live Sybilion/FRED. Frontend builds on mock.
"""
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
        "endpoints": ["/scope", "/calendar", "/signals", "/strongest",
                      "/forecast/{pair}", "/strategy", "/backtest", "/shock"],
    }


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
