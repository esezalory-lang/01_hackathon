"""
Walk-forward monthly FX backtest (Sybilion-driven, no Qwen pre-filter).

For each target month in 2026 (Jan..May):
  1. Truncate every one of the 28 major pairs to the month BEFORE the target.
  2. Send all 28 to Sybilion (1-month horizon) -> predicted next-month level.
  3. Rank: BUY = predicted up, SELL = predicted down, by confidence.
  4. Emit the 6 picks (top 3 BUY + top 3 SELL) and the single strongest BUY and
     strongest SELL. The realized (actual) value is attached so the partner can
     score the call.

Output is a per-month track record -> data/monthly_backtest.json (partner hand-off).
"""
import datetime as dt
import json
import os

import config
import pairs28
from pipeline.step2_forecast import score_confidence


def _provider(use_mock):
    if use_mock:
        import mock_sybilion
        return mock_sybilion
    import sybilion_client
    return sybilion_client


def _forecast_pair_for_month(pair, info, target_month, provider, use_mock, shock):
    """Forecast one pair for `target_month` using only history strictly before it."""
    hist = [(d, v) for d, v in info["series"] if d < target_month]
    if len(hist) < 40:
        return None  # not enough history for Sybilion at this month
    actual = next((v for d, v in info["series"] if d == target_month), None)
    timeseries = dict(hist)
    current_price = hist[-1][1]

    meta = pairs28.pair_meta(pair, info)
    raw = provider.forecast_pair(meta, timeseries=timeseries, current_price=current_price,
                                 shock=shock, prefer_series=True,
                                 soft_horizon=config.SOFT_HORIZON_BACKTEST)
    raw.setdefault("pair", pair)
    raw.setdefault("slug", info["slug"])
    scored = score_confidence(raw)

    predicted = scored["forecast"][-1]["p50"]
    side = "BUY" if scored["direction"] == "UP" else "SELL"
    realized_dir = None
    hit = None
    if actual is not None:
        realized_dir = "UP" if actual > current_price else "DOWN"
        hit = (realized_dir == scored["direction"])
    return {
        "pair": pair,
        "side": side,
        "signal": scored["signal"],
        "confidence": scored["confidence"],
        "direction": scored["direction"],
        "current_price": round(current_price, 6),
        "predicted_next_month": round(predicted, 6),
        "actual_next_month": round(actual, 6) if actual is not None else None,
        "realized_direction": realized_dir,
        "direction_hit": hit,
    }


def _rank_month(rows):
    buys = sorted([r for r in rows if r["side"] == "BUY"],
                  key=lambda r: r["confidence"], reverse=True)
    sells = sorted([r for r in rows if r["side"] == "SELL"],
                   key=lambda r: r["confidence"], reverse=True)
    return {"buy": buys[:3], "sell": sells[:3]}


def run_monthly_backtest(use_mock=None, shock=None, months=None):
    if use_mock is None:
        use_mock = config.USE_MOCK
    months = months or config.BACKTEST_MONTHS
    provider = _provider(use_mock)

    pairs_all = pairs28.build_all(start=config.BACKTEST_FRED_START)

    per_month = []
    for tm in months:
        rows = []
        for pair, info in pairs_all.items():
            r = _forecast_pair_for_month(pair, info, tm, provider, use_mock, shock)
            if r:
                rows.append(r)
        ranked = _rank_month(rows)
        buys, sells = ranked["buy"], ranked["sell"]
        per_month.append({
            "month": tm[:7],
            "n_pairs_forecast": len(rows),
            "buy": buys,    # top 3 BUY
            "sell": sells,  # top 3 SELL
            "headline": (
                f"{tm[:7]}  BUY " + ", ".join(f"{b['pair']}({b['confidence']:.0f})" for b in buys)
                + "  |  SELL " + ", ".join(f"{s['pair']}({s['confidence']:.0f})" for s in sells)
            ),
        })

    # Track-record summary: direction hit-rate over all 3+3 picks across months.
    all_picks = [r for m in per_month for r in (m["buy"] + m["sell"])]
    scored = [c for c in all_picks if c["direction_hit"] is not None]
    hit_rate = round(sum(c["direction_hit"] for c in scored) / len(scored), 3) if scored else None

    payload = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "use_mock": use_mock,
        "shock": shock,
        "horizon_months": config.SOFT_HORIZON_BACKTEST,
        "universe": len(pairs_all),
        "months": per_month,
        "headline_direction_hit_rate": hit_rate,
    }
    os.makedirs(config.DATA_DIR, exist_ok=True)
    path = os.path.join(config.DATA_DIR, "monthly_backtest.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    payload["handoff_path"] = path
    return payload


if __name__ == "__main__":
    out = run_monthly_backtest(use_mock=True)
    for m in out["months"]:
        print(" •", m["headline"], f"[{m['n_pairs_forecast']} pairs]")
    print("headline direction hit-rate:", out["headline_direction_hit_rate"])
    print("handoff ->", out["handoff_path"])
