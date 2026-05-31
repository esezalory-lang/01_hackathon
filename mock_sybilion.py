"""
mock_sybilion.py — realistic mock FX forecasts, same shape as the real client.

Surface mirrors sybilion_client:
    forecast_pair(pair_meta, timeseries=None, current_price=None, shock=None) -> D2

The mock ignores the incoming timeseries and returns canned-but-realistic output
keyed by pair slug. Numbers are tuned so score_confidence() (step2) yields
EUR/USD and USD/JPY as the strongest pairs at baseline, with shocks flipping
others (e.g. china_deval -> USD/CNY becomes STRONG).
"""
import copy

# 3-month forecasts (horizon = config.SOFT_HORIZON). The scorer reads the LAST
# step (month 3). `history` is the recent monthly tail for charting.
_BASE = {
    "eur_usd": {
        "quote": "USD per EUR", "current_price": 1.117,
        "history": [
            {"date": "2025-07-01", "value": 1.162}, {"date": "2025-08-01", "value": 1.168},
            {"date": "2025-09-01", "value": 1.152}, {"date": "2025-10-01", "value": 1.141},
            {"date": "2025-11-01", "value": 1.128}, {"date": "2025-12-01", "value": 1.117},
        ],
        "forecast": [
            {"month": 1, "p10": 1.088, "p50": 1.100, "p90": 1.118},
            {"month": 2, "p10": 1.060, "p50": 1.082, "p90": 1.104},
            {"month": 3, "p10": 1.038, "p50": 1.060, "p90": 1.086},
        ],
        "drivers": [
            {"name": "ECB policy", "importance": 0.36, "direction": "down"},
            {"name": "Fed funds", "importance": 0.28, "direction": "up"},
            {"name": "Eurozone CPI", "importance": 0.18, "direction": "up"},
            {"name": "German PMI", "importance": 0.10, "direction": "down"},
            {"name": "US NFP", "importance": 0.08, "direction": "up"},
        ],
        "backtest": {"mape": 4.0, "baseline_mape": 9.1},
    },
    "usd_jpy": {
        "quote": "JPY per USD", "current_price": 157.0,
        "history": [
            {"date": "2025-07-01", "value": 161.2}, {"date": "2025-08-01", "value": 159.8},
            {"date": "2025-09-01", "value": 158.4}, {"date": "2025-10-01", "value": 158.9},
            {"date": "2025-11-01", "value": 157.6}, {"date": "2025-12-01", "value": 157.0},
        ],
        "forecast": [
            {"month": 1, "p10": 152, "p50": 154, "p90": 158},
            {"month": 2, "p10": 147, "p50": 151, "p90": 156},
            {"month": 3, "p10": 143, "p50": 148, "p90": 153},
        ],
        "drivers": [
            {"name": "BOJ policy", "importance": 0.40, "direction": "down"},
            {"name": "US 10Y yield", "importance": 0.25, "direction": "up"},
            {"name": "Japan CPI", "importance": 0.16, "direction": "down"},
            {"name": "Risk sentiment", "importance": 0.11, "direction": "up"},
            {"name": "Fed funds", "importance": 0.08, "direction": "up"},
        ],
        "backtest": {"mape": 5.0, "baseline_mape": 11.4},
    },
    "usd_cny": {
        "quote": "CNY per USD", "current_price": 7.20,
        "history": [
            {"date": "2025-07-01", "value": 7.18}, {"date": "2025-08-01", "value": 7.17},
            {"date": "2025-09-01", "value": 7.19}, {"date": "2025-10-01", "value": 7.21},
            {"date": "2025-11-01", "value": 7.20}, {"date": "2025-12-01", "value": 7.20},
        ],
        "forecast": [
            {"month": 1, "p10": 7.18, "p50": 7.21, "p90": 7.26},
            {"month": 2, "p10": 7.18, "p50": 7.22, "p90": 7.29},
            {"month": 3, "p10": 7.18, "p50": 7.23, "p90": 7.32},
        ],
        "drivers": [
            {"name": "PBOC fixing", "importance": 0.38, "direction": "up"},
            {"name": "China PMI", "importance": 0.22, "direction": "down"},
            {"name": "US-China trade", "importance": 0.20, "direction": "up"},
            {"name": "Export controls", "importance": 0.12, "direction": "up"},
            {"name": "Fed funds", "importance": 0.08, "direction": "up"},
        ],
        "backtest": {"mape": 6.0, "baseline_mape": 10.2},
    },
    "usd_krw": {
        "quote": "KRW per USD", "current_price": 1380.0,
        "history": [
            {"date": "2025-07-01", "value": 1372}, {"date": "2025-08-01", "value": 1388},
            {"date": "2025-09-01", "value": 1395}, {"date": "2025-10-01", "value": 1384},
            {"date": "2025-11-01", "value": 1379}, {"date": "2025-12-01", "value": 1380},
        ],
        "forecast": [
            {"month": 1, "p10": 1350, "p50": 1388, "p90": 1430},
            {"month": 2, "p10": 1340, "p50": 1395, "p90": 1465},
            {"month": 3, "p10": 1330, "p50": 1400, "p90": 1495},
        ],
        "drivers": [
            {"name": "BOK policy", "importance": 0.30, "direction": "up"},
            {"name": "Semis exports", "importance": 0.26, "direction": "down"},
            {"name": "Risk sentiment", "importance": 0.20, "direction": "up"},
            {"name": "Fed funds", "importance": 0.14, "direction": "up"},
            {"name": "KOSPI flows", "importance": 0.10, "direction": "down"},
        ],
        "backtest": {"mape": 9.0, "baseline_mape": 15.5},
    },
    "usd_twd": {
        "quote": "TWD per USD", "current_price": 32.5,
        "history": [
            {"date": "2025-07-01", "value": 32.1}, {"date": "2025-08-01", "value": 32.3},
            {"date": "2025-09-01", "value": 32.6}, {"date": "2025-10-01", "value": 32.4},
            {"date": "2025-11-01", "value": 32.5}, {"date": "2025-12-01", "value": 32.5},
        ],
        "forecast": [
            {"month": 1, "p10": 32.2, "p50": 32.8, "p90": 33.5},
            {"month": 2, "p10": 32.1, "p50": 33.0, "p90": 33.9},
            {"month": 3, "p10": 32.1, "p50": 33.1, "p90": 34.2},
        ],
        "drivers": [
            {"name": "TSMC flows", "importance": 0.34, "direction": "down"},
            {"name": "CBC policy", "importance": 0.24, "direction": "up"},
            {"name": "Tech demand", "importance": 0.20, "direction": "down"},
            {"name": "Fed funds", "importance": 0.12, "direction": "up"},
            {"name": "Risk sentiment", "importance": 0.10, "direction": "up"},
        ],
        "backtest": {"mape": 7.0, "baseline_mape": 12.1},
    },
}

# Shock overrides: each replaces a pair's forecast (and drivers/backtest) so the
# demo shows a confidence shift live.
_SHOCKS = {
    # BOJ surprise hike -> yen surges -> USD/JPY confidence climbs further.
    "boj_hike": {
        "usd_jpy": {
            "forecast": [
                {"month": 1, "p10": 148, "p50": 150, "p90": 154},
                {"month": 2, "p10": 143, "p50": 145, "p90": 150},
                {"month": 3, "p10": 134, "p50": 140, "p90": 146},
            ],
            "drivers": [
                {"name": "BOJ policy", "importance": 0.58, "direction": "down"},
                {"name": "Japan CPI", "importance": 0.18, "direction": "down"},
                {"name": "US 10Y yield", "importance": 0.13, "direction": "up"},
                {"name": "Risk sentiment", "importance": 0.07, "direction": "up"},
                {"name": "Fed funds", "importance": 0.04, "direction": "up"},
            ],
            "backtest": {"mape": 5.0, "baseline_mape": 11.4},
        },
    },
    # ECB cut -> EUR weakens -> EUR/USD move deepens.
    "ecb_cut": {
        "eur_usd": {
            "forecast": [
                {"month": 1, "p10": 1.078, "p50": 1.090, "p90": 1.108},
                {"month": 2, "p10": 1.045, "p50": 1.060, "p90": 1.085},
                {"month": 3, "p10": 1.005, "p50": 1.030, "p90": 1.060},
            ],
            "drivers": [
                {"name": "ECB policy", "importance": 0.55, "direction": "down"},
                {"name": "Eurozone CPI", "importance": 0.20, "direction": "down"},
                {"name": "Fed funds", "importance": 0.15, "direction": "up"},
                {"name": "German PMI", "importance": 0.06, "direction": "down"},
                {"name": "US NFP", "importance": 0.04, "direction": "up"},
            ],
            "backtest": {"mape": 4.0, "baseline_mape": 9.1},
        },
    },
    # China devaluation -> USD/CNY jumps, bands widen -> flips WEAK to STRONG.
    "china_deval": {
        "usd_cny": {
            "forecast": [
                {"month": 1, "p10": 7.25, "p50": 7.35, "p90": 7.50},
                {"month": 2, "p10": 7.30, "p50": 7.46, "p90": 7.68},
                {"month": 3, "p10": 7.35, "p50": 7.55, "p90": 7.85},
            ],
            "drivers": [
                {"name": "PBOC fixing", "importance": 0.52, "direction": "up"},
                {"name": "US-China trade", "importance": 0.24, "direction": "up"},
                {"name": "Export controls", "importance": 0.14, "direction": "up"},
                {"name": "China PMI", "importance": 0.06, "direction": "down"},
                {"name": "Fed funds", "importance": 0.04, "direction": "up"},
            ],
            "backtest": {"mape": 8.0, "baseline_mape": 14.0},
        },
    },
}

SHOCK_TYPES = list(_SHOCKS.keys())


def _synth_from_series(ts, horizon=1):
    """Realistic mock forecast from a real monthly series: drift + vol-scaled bands.
    Lets the 28 majors produce varied STRONG/WEAK signals in mock mode."""
    import statistics
    items = sorted(ts.items())
    vals = [v for _, v in items]
    cur = vals[-1]
    recent = vals[-7:] if len(vals) >= 7 else vals
    drift = (recent[-1] - recent[0]) / max(1, len(recent) - 1)
    diffs = [vals[i] - vals[i - 1] for i in range(max(1, len(vals) - 12), len(vals))]
    vol = statistics.pstdev(diffs) if len(diffs) > 1 else abs(cur) * 0.01
    forecast = []
    for m in range(1, horizon + 1):
        p50 = cur + drift * m
        spread = 1.2816 * vol * (m ** 0.5)        # ~80% band (p10..p90)
        forecast.append({"month": m, "p10": round(p50 - spread, 6),
                         "p50": round(p50, 6), "p90": round(p50 + spread, 6)})
    mape = round(min(40.0, max(2.0, (vol / cur) * 100 * 3)), 1) if cur else 12.0
    return {
        "current_price": round(cur, 6),
        "history": [{"date": d, "value": v} for d, v in items[-6:]],
        "forecast": forecast,
        "drivers": [],
        "backtest": {"mape": mape, "baseline_mape": round(mape * 1.6, 1)},
    }


def _generic(pair_meta):
    """Neutral, low-confidence forecast for a pair we have no canned data for.
    Keeps the mock from crashing when Layer 1 picks a pair outside the 5 above."""
    cp = 1.0
    return {
        "quote": pair_meta.get("quote") if isinstance(pair_meta, dict) else None,
        "current_price": cp,
        "history": [],
        "forecast": [
            {"month": 1, "p10": cp * 0.99, "p50": cp, "p90": cp * 1.01},
            {"month": 2, "p10": cp * 0.985, "p50": cp, "p90": cp * 1.015},
            {"month": 3, "p10": cp * 0.98, "p50": cp, "p90": cp * 1.02},
        ],
        "drivers": [],
        "backtest": {"mape": 10.0, "baseline_mape": 15.0},
    }


def forecast_pair(pair_meta, timeseries=None, current_price=None, shock=None,
                  prefer_series=False, **kwargs):
    """Return a normalized D2 forecast for one pair.

    prefer_series=True forces a synthetic forecast from the supplied timeseries
    even for canned slugs — required by the walk-forward backtest, which feeds
    truncated history per month and must NOT use static canned data.
    """
    slug = pair_meta["slug"] if isinstance(pair_meta, dict) else pair_meta
    from config import SOFT_HORIZON_BACKTEST
    if prefer_series and timeseries:
        base = _synth_from_series(timeseries, horizon=SOFT_HORIZON_BACKTEST)
    elif slug in _BASE:
        base = copy.deepcopy(_BASE[slug])
    elif timeseries:
        # 28-major path: synthesize from the real series passed in.
        base = _synth_from_series(timeseries, horizon=SOFT_HORIZON_BACKTEST)
    else:
        base = _generic(pair_meta)

    override = _SHOCKS.get(shock, {}).get(slug) if shock else None
    if override:
        base.update(copy.deepcopy(override))

    base["pair"] = pair_meta["pair"] if isinstance(pair_meta, dict) else slug
    base["slug"] = slug
    base["fred_id"] = pair_meta.get("fred_id") if isinstance(pair_meta, dict) else None
    base["source"] = "mock"
    base["shock"] = shock
    return base
