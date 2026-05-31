"""
LIVE Sybilion walk-forward for the remaining 2026 months (Feb..May), merged with
the already-paid Jan result, producing the full live track record:
    data/monthly_backtest_live.json

Submits every (month, pair) job in PARALLEL, polls to completion, scores against
the realized value, ranks strongest BUY/SELL per month.
"""
import json
import os
import time

import config
import pairs28
import sybilion_client as sc
from pipeline.step2_forecast import score_confidence

MONTHS_TO_RUN = ["2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01"]
JAN_FILE = os.path.join(config.DATA_DIR, "monthly_backtest_jan2026_live.json")
OUT = os.path.join(config.DATA_DIR, "monthly_backtest_live.json")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def _row(pair, scored, cur, actual):
    pred = scored["forecast"][-1]["p50"]
    side = "BUY" if scored["direction"] == "UP" else "SELL"
    hit = (("UP" if actual > cur else "DOWN") == scored["direction"]) if actual else None
    return {"pair": pair, "side": side, "signal": scored["signal"],
            "confidence": scored["confidence"], "direction": scored["direction"],
            "current_price": round(cur, 6), "predicted_next_month": round(pred, 6),
            "actual_next_month": round(actual, 6) if actual else None, "direction_hit": hit}


def _rank(rows, month):
    buys = sorted([r for r in rows if r["side"] == "BUY"], key=lambda r: r["confidence"], reverse=True)
    sells = sorted([r for r in rows if r["side"] == "SELL"], key=lambda r: r["confidence"], reverse=True)
    sb, ss = (buys[0] if buys else None), (sells[0] if sells else None)
    return {"month": month[:7], "n_pairs_forecast": len(rows),
            "strongest_buy": sb, "strongest_sell": ss, "six": buys[:3] + sells[:3],
            "headline": (f"{month[:7]}  BUY {sb['pair'] if sb else '-'} "
                         f"(conf {sb['confidence'] if sb else '-'})  |  "
                         f"SELL {ss['pair'] if ss else '-'} (conf {ss['confidence'] if ss else '-'})")}


def main():
    allp = pairs28.build_all(start=config.BACKTEST_FRED_START)

    # 1) submit all (month, pair) jobs
    jobs, meta, ctx = {}, {}, {}
    for tm in MONTHS_TO_RUN:
        for pair, info in allp.items():
            hist = [(d, v) for d, v in info["series"] if d < tm]
            if len(hist) < 40:
                continue
            actual = next((v for d, v in info["series"] if d == tm), None)
            m = pairs28.pair_meta(pair, info)
            key = (tm, pair)
            meta[key] = m
            ctx[key] = {"current": hist[-1][1], "actual": actual}
            try:
                jobs[key] = sc.submit(
                    {d: v for d, v in hist}, title=f"{pair} monthly exchange rate ({m['quote']})",
                    description=f"{pair} monthly avg from FRED legs, walk-forward {tm} target.",
                    soft_horizon=config.SOFT_HORIZON_BACKTEST, backtest=True, driver_limit=0)
            except Exception as e:
                log(f"submit FAILED {tm} {pair}: {e}")
        log(f"submitted month {tm[:7]} ({sum(1 for k in jobs if k[0]==tm)} pairs)")
    log(f"submitted {len(jobs)} jobs total; polling...")

    # 2) poll
    results, pending = {}, set(jobs)
    deadline = time.time() + 45 * 60
    while pending and time.time() < deadline:
        time.sleep(30)
        for key in list(pending):
            try:
                r = sc.requests.get(f"{config.SYBILION_BASE_URL}/api/v1/forecasts/{jobs[key]}",
                                    headers=sc.HEADERS, timeout=20).json()
            except Exception:
                continue
            if r.get("status") == "completed":
                results[key] = True
                pending.discard(key)
            elif r.get("status") == "failed":
                pending.discard(key)
                log(f"FAILED {key}")
        log(f"... {len(pending)} pending, {len(results)} done")

    # 3) read + score, grouped by month
    by_month = {tm: [] for tm in MONTHS_TO_RUN}
    for key in results:
        tm, pair = key
        try:
            fj = sc.read_artifacts(jobs[key], "forecast.json")
            mj = None
            try:
                mj = sc.read_artifacts(jobs[key], "backtest_metrics.json")
            except Exception:
                pass
            d2 = sc._normalize(meta[key], fj, ctx[key]["current"], mj)
            by_month[tm].append(_row(pair, score_confidence(d2), ctx[key]["current"], ctx[key]["actual"]))
        except Exception as e:
            log(f"read/score err {key}: {e}")

    months = [_rank(by_month[tm], tm) for tm in MONTHS_TO_RUN]

    # 4) merge already-paid Jan result
    if os.path.exists(JAN_FILE):
        j = json.load(open(JAN_FILE))
        months.insert(0, {"month": "2026-01", "n_pairs_forecast": j["n_pairs_forecast"],
                          "strongest_buy": j["strongest_buy"], "strongest_sell": j["strongest_sell"],
                          "six": j["six"],
                          "headline": (f"2026-01  BUY {j['strongest_buy']['pair']} "
                                       f"(conf {j['strongest_buy']['confidence']})  |  "
                                       f"SELL {j['strongest_sell']['pair']} "
                                       f"(conf {j['strongest_sell']['confidence']})")})

    # 5) overall headline hit-rate (strongest buy+sell across months)
    calls = [m["strongest_buy"] for m in months if m["strongest_buy"]] + \
            [m["strongest_sell"] for m in months if m["strongest_sell"]]
    scored = [c for c in calls if c.get("direction_hit") is not None]
    hr = round(sum(c["direction_hit"] for c in scored) / len(scored), 3) if scored else None

    payload = {"live": True, "horizon_months": config.SOFT_HORIZON_BACKTEST,
               "universe": len(allp), "months": months, "headline_direction_hit_rate": hr}
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=2)
    log(f"DONE -> {OUT}")
    for m in months:
        log(" " + m["headline"])
    log(f"headline hit-rate {hr} over {len(scored)} calls")


if __name__ == "__main__":
    main()
