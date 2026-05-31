"""
One-off LIVE Sybilion validation for the Jan-2026 walk-forward month.

Submits all 28 major pairs in PARALLEL (history truncated to Dec 2025, horizon 1),
polls to completion, normalizes + scores, ranks strongest BUY/SELL, scores against
the realized Jan-2026 value, and writes data/monthly_backtest_jan2026_live.json.
"""
import json
import os
import time

import config
import pairs28
import sybilion_client as sc
from pipeline.step2_forecast import score_confidence

TARGET = "2026-01-01"
OUT = os.path.join(config.DATA_DIR, "monthly_backtest_jan2026_live.json")
EXISTING = {"EUR/USD": os.environ.get("EURUSD_JOB")}  # reuse smoke-test job if set


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    allp = pairs28.build_all(start=config.BACKTEST_FRED_START)
    jobs, meta, ctx = {}, {}, {}

    # 1) submit all 28
    for pair, info in allp.items():
        hist = [(d, v) for d, v in info["series"] if d < TARGET]
        actual = next((v for d, v in info["series"] if d == TARGET), None)
        ts = {d: v for d, v in hist}
        m = pairs28.pair_meta(pair, info)
        meta[pair] = m
        ctx[pair] = {"current": hist[-1][1], "actual": actual}
        try:
            jid = EXISTING.get(pair) or sc.submit(
                ts, title=f"{pair} monthly exchange rate ({m['quote']})",
                description=f"{pair} monthly avg from FRED legs, walk-forward {TARGET} target.",
                soft_horizon=config.SOFT_HORIZON_BACKTEST, backtest=True, driver_limit=0)
            jobs[pair] = jid
            log(f"submitted {pair:9s} -> {jid}")
        except Exception as e:
            log(f"submit FAILED {pair}: {e}")
    log(f"submitted {len(jobs)} jobs; polling...")

    # 2) poll to completion
    results, pending = {}, set(jobs)
    deadline = time.time() + 45 * 60
    while pending and time.time() < deadline:
        time.sleep(30)
        for pair in list(pending):
            try:
                r = sc.requests.get(
                    f"{config.SYBILION_BASE_URL}/api/v1/forecasts/{jobs[pair]}",
                    headers=sc.HEADERS, timeout=20).json()
            except Exception as e:
                log(f"poll err {pair}: {e}")
                continue
            status = r.get("status")
            if status == "completed":
                results[pair] = r
                pending.discard(pair)
                log(f"completed {pair} ({len(results)}/{len(jobs)})")
            elif status == "failed":
                pending.discard(pair)
                log(f"FAILED {pair}: {r}")
        log(f"... {len(pending)} pending")

    # 3) read + normalize + score
    rows = []
    for pair, _r in results.items():
        try:
            fj = sc.read_artifacts(jobs[pair], "forecast.json")
            mj = None
            try:
                mj = sc.read_artifacts(jobs[pair], "backtest_metrics.json")
            except Exception:
                pass
            d2 = sc._normalize(meta[pair], fj, ctx[pair]["current"], mj)
            scored = score_confidence(d2)
            cur, actual = ctx[pair]["current"], ctx[pair]["actual"]
            pred = scored["forecast"][-1]["p50"]
            side = "BUY" if scored["direction"] == "UP" else "SELL"
            hit = (("UP" if actual > cur else "DOWN") == scored["direction"]) if actual else None
            rows.append({
                "pair": pair, "side": side, "signal": scored["signal"],
                "confidence": scored["confidence"], "direction": scored["direction"],
                "current_price": round(cur, 6), "predicted_next_month": round(pred, 6),
                "actual_next_month": round(actual, 6) if actual else None,
                "direction_hit": hit,
            })
        except Exception as e:
            log(f"read/score err {pair}: {e}")

    buys = sorted([r for r in rows if r["side"] == "BUY"], key=lambda r: r["confidence"], reverse=True)
    sells = sorted([r for r in rows if r["side"] == "SELL"], key=lambda r: r["confidence"], reverse=True)
    scored_hits = [r for r in rows if r["direction_hit"] is not None]
    payload = {
        "month": "2026-01", "live": True, "horizon_months": config.SOFT_HORIZON_BACKTEST,
        "n_pairs_forecast": len(rows), "n_submitted": len(jobs),
        "strongest_buy": buys[0] if buys else None,
        "strongest_sell": sells[0] if sells else None,
        "six": buys[:3] + sells[:3],
        "all": sorted(rows, key=lambda r: r["confidence"], reverse=True),
        "direction_hit_rate": round(sum(r["direction_hit"] for r in scored_hits) / len(scored_hits), 3)
        if scored_hits else None,
    }
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=2)
    log(f"DONE -> {OUT}")
    sb, ss = payload["strongest_buy"], payload["strongest_sell"]
    log(f"STRONGEST BUY : {sb['pair'] if sb else '-'} conf={sb['confidence'] if sb else '-'} hit={sb['direction_hit'] if sb else '-'}")
    log(f"STRONGEST SELL: {ss['pair'] if ss else '-'} conf={ss['confidence'] if ss else '-'} hit={ss['direction_hit'] if ss else '-'}")
    log(f"hit-rate {payload['direction_hit_rate']} over {len(scored_hits)} pairs")


if __name__ == "__main__":
    main()
