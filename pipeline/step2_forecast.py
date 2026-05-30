"""
Layer 2 — Forecast + confidence ranking.

For each scoped pair:
  1. Build the monthly series: FRED history (2023->now) with the CURRENT month
     refreshed from the hourly feed (live mode).
  2. Forecast it via Sybilion (filters.limit=0, 3-month horizon) — or the mock.
  3. Score CONFIDENCE from the 3-month bands + backtest, and tag STRONG/WEAK.

`select_strongest()` returns only the pairs the forecaster is most confident in.
"""
import math

import config


# --------------------------------------------------------------------------
# Confidence scoring
# --------------------------------------------------------------------------
def score_confidence(forecast):
    """Add band_width, price_move, direction, confidence (0-100) and signal.

    Confidence is high when there is a decisive directional move relative to the
    forecast uncertainty AND the backtest error is low.
    """
    last = forecast["forecast"][-1]
    p10, p50, p90 = last["p10"], last["p50"], last["p90"]
    current = forecast["current_price"]

    band_width = (p90 - p10) / p50 if p50 else float("inf")
    price_move = abs(p50 - current) / current if current else 0.0
    mape = (forecast.get("backtest") or {}).get("mape")

    conviction = price_move / (band_width + 1e-6)
    accuracy = (1 - min(mape, 50) / 50) if mape is not None else 0.7  # neutral if no backtest
    confidence = round(100 * math.tanh(conviction) * accuracy, 1)

    return {
        **forecast,
        "band_width": round(band_width, 3),
        "price_move": round(price_move, 3),
        "direction": "UP" if p50 > current else "DOWN",
        "mape": mape,
        "confidence": confidence,
        "signal": "STRONG" if confidence >= config.CONFIDENCE_THRESHOLD else "WEAK",
    }


# --------------------------------------------------------------------------
# Series construction (live mode)
# --------------------------------------------------------------------------
def build_series(pair_meta):
    """Return (timeseries_map, current_price, source) for one pair from FRED+hourly."""
    import fred_client
    import hourly_fx

    monthly = fred_client.get_monthly(pair_meta["fred_id"])  # [(YYYY-MM-01, val)]
    ts = {d: v for d, v in monthly}
    current_price = monthly[-1][1] if monthly else None
    source = "fred_monthly"

    # Refresh the current month with the hourly feed.
    value, src = hourly_fx.get_current_month_value(pair_meta["pair"])
    if value is not None and monthly:
        latest_month = monthly[-1][0]  # YYYY-MM-01
        ts[latest_month] = value
        current_price = value
        source = src
    return ts, current_price, source


# --------------------------------------------------------------------------
# Provider dispatch
# --------------------------------------------------------------------------
def _provider(use_mock):
    if use_mock:
        import mock_sybilion
        return mock_sybilion
    import sybilion_client
    return sybilion_client


def forecast_pair(pair_meta, use_mock=None, shock=None):
    """Forecast one scoped pair and attach confidence."""
    if use_mock is None:
        use_mock = config.USE_MOCK
    provider = _provider(use_mock)

    if use_mock:
        raw = provider.forecast_pair(pair_meta, timeseries=None, current_price=None, shock=shock)
    else:
        ts, current_price, source = build_series(pair_meta)
        raw = provider.forecast_pair(pair_meta, timeseries=ts, current_price=current_price,
                                     shock=shock)
        raw.setdefault("source", source)

    raw.setdefault("pair", pair_meta["pair"])
    raw.setdefault("slug", pair_meta["slug"])
    raw.setdefault("fred_id", pair_meta.get("fred_id"))
    return score_confidence(raw)


def run(scoped_pairs=None, use_mock=None, shock=None):
    """Forecast + score every scoped pair; return list sorted by confidence desc."""
    if use_mock is None:
        use_mock = config.USE_MOCK
    if scoped_pairs is None:
        from pipeline.step1_scope import scope_pairs
        scoped_pairs = scope_pairs()
    results = [forecast_pair(p, use_mock=use_mock, shock=shock) for p in scoped_pairs]
    results.sort(key=lambda r: r["confidence"], reverse=True)
    for rank, r in enumerate(results, start=1):
        r["rank"] = rank
    return results


def select_strongest(results):
    """The pairs to actually act on: confidence >= threshold, else the top one."""
    strong = [r for r in results if r["confidence"] >= config.CONFIDENCE_THRESHOLD]
    if not strong and results:
        strong = [results[0]]
    for r in results:
        r["selected"] = r in strong
    return strong


if __name__ == "__main__":
    res = run(use_mock=True)
    for r in res:
        print(f"  {r['pair']:9s} conf={r['confidence']:5.1f} {r['signal']:6s} "
              f"dir={r['direction']} bw={r['band_width']:.3f} move={r['price_move']:.3f}")
    print("strongest:", [r["pair"] for r in select_strongest(res)])
