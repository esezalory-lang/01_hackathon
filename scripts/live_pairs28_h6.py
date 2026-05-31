"""
LIVE Sybilion 6-month forecast for all 28 major pairs, 84-month window, backtest ON.

84 = 72 (horizon-6 minimum) + 12 (hindcast holdout) -> supports backtest + MAPE.
For each pair: forecast 6 months ahead, score direction (BUY/SELL) + confidence,
and read the backtest MAPE. Ranks by accuracy and returns only the TOP PERFORMERS.

Writes data/pairs28_h6_live.json.
"""
import json
import os
import time

import config
import pairs28
import sybilion_client as sc
from pipeline.step2_forecast import score_confidence

START = "2018-06-01"   # >= 84 monthly points available
LOOKBACK = 84
HORIZON = 6
TOP_N = 8
OUT = os.path.join(config.DATA_DIR, "pairs28_h6_live.json")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def _mape(job_id):
    try:
        bm = sc.read_artifacts(job_id, "backtest_metrics.json").get("data", {})
        for win in ("12m", "6m", "24m", "60m"):
            v = bm.get(win, {}).get("metrics", {}).get("MAPE")
            if v is not None:
                return round(v, 3)
    except Exception:
        pass
    return None


def main():
    allp = pairs28.build_all(start=START)
    jobs, ctx, meta = {}, {}, {}

    # 1) submit all 28 (last 84 months each)
    for pair, info in allp.items():
        hist = info["series"][-LOOKBACK:]
        ts = {d: v for d, v in hist}
        ctx[pair] = {"current": hist[-1][1], "current_date": hist[-1][0], "n": len(ts)}
        m = pairs28.pair_meta(pair, info)
        meta[pair] = m
        try:
            jobs[pair] = sc.submit(
                ts, title=f"{pair} monthly exchange rate, {LOOKBACK}-month window",
                description=f"{pair} monthly avg from FRED legs, last {LOOKBACK} months, "
                            f"{HORIZON}-month horizon with backtest.",
                soft_horizon=HORIZON, backtest=True, driver_limit=0)
        except Exception as e:
            log(f"submit FAILED {pair}: {e}")
    log(f"submitted {len(jobs)} jobs ({LOOKBACK}m, h{HORIZON}, backtest); polling...")

    # 2) poll
    done, pending = set(), set(jobs)
    deadline = time.time() + 40 * 60
    while pending and time.time() < deadline:
        time.sleep(30)
        for pair in list(pending):
            try:
                r = sc.requests.get(f"{config.SYBILION_BASE_URL}/api/v1/forecasts/{jobs[pair]}",
                                    headers=sc.HEADERS, timeout=20).json()
            except Exception:
                continue
            st = r.get("status")
            if st == "completed":
                done.add(pair); pending.discard(pair)
            elif st == "failed":
                pending.discard(pair)
                log(f"FAILED {pair}: {r.get('pipeline_error', {}).get('error', '')[:50]}")
        log(f"... {len(pending)} pending, {len(done)} done")

    # 3) read + score
    rows = []
    for pair in done:
        try:
            fj = sc.read_artifacts(jobs[pair], "forecast.json")
            d2 = sc._normalize(meta[pair], fj, ctx[pair]["current"])
            mape = _mape(jobs[pair])
            d2["backtest"] = {"mape": mape}
            scored = score_confidence(d2)
            cur = ctx[pair]["current"]
            h6 = scored["forecast"][-1]["p50"]
            rows.append({
                "pair": pair, "side": "BUY" if scored["direction"] == "UP" else "SELL",
                "signal": scored["signal"], "confidence": scored["confidence"],
                "mape": mape, "current": round(cur, 6), "horizon6_p50": round(h6, 6),
                "move_pct": round((h6 - cur) / cur * 100, 2) if cur else None,
            })
        except Exception as e:
            log(f"read err {pair}: {e}")

    # 4) rank: top performers = lowest backtest MAPE (most reliable forecasts)
    ranked = sorted([r for r in rows if r["mape"] is not None], key=lambda r: r["mape"])
    no_mape = [r for r in rows if r["mape"] is None]
    top = ranked[:TOP_N]

    payload = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "live": True,
               "window_months": LOOKBACK, "horizon_months": HORIZON, "universe": len(allp),
               "n_forecast": len(rows), "top_performers": top, "all_ranked": ranked + no_mape}
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=2)
    log(f"DONE -> {OUT}  ({len(rows)}/{len(jobs)} forecast)")
    log(f"TOP {len(top)} PERFORMERS (lowest backtest MAPE):")
    for i, r in enumerate(top, 1):
        log(f"  {i}. {r['pair']:9s} {r['signal']:6s} {r['side']:4s}  MAPE={r['mape']:5.2f}%  "
            f"conf={r['confidence']:5.1f}  6mo move {r['move_pct']:+.2f}%")


if __name__ == "__main__":
    main()
