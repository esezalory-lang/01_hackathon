"""
LIVE Sybilion walk-forward on EUR/USD from FRED (DEXUSEU), all history from 2000,
LONGER horizon (6 months). For each target month Jan->May 2026:
  - feed all monthly history up to the prior month,
  - forecast 6 months ahead,
  - signal = direction over the 6-month horizon (BUY if up, SELL if down) + confidence,
  - also score the next-month forecast point vs the realized FRED value.

Writes data/eurusd_fred_loop_live.json.
"""
import json
import os
import time

import config
import fred_client
import sybilion_client as sc
from pipeline.step2_forecast import score_confidence

START = "2000-01-01"
HORIZON = 6
LOOKBACK = 84  # 7 years. horizon-6 needs 72 to forecast; backtest=True adds a ~12-month hindcast
               # holdout on top, so 84 (72+12) is the window that supports backtest + MAPE.
TARGETS = ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01"]
OUT = os.path.join(config.DATA_DIR, "eurusd_fred_loop_live.json")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    series = fred_client.get_monthly("DEXUSEU", start=START)  # [(YYYY-MM-01, val)]
    log(f"FRED DEXUSEU: {len(series)} monthly pts {series[0][0]}..{series[-1][0]}")

    jobs, ctx = {}, {}
    for tm in TARGETS:
        hist = [(d, v) for d, v in series if d < tm][-LOOKBACK:]  # last 5 years only
        actual = next((v for d, v in series if d == tm), None)
        ts = {d: v for d, v in hist}
        ctx[tm] = {"current": hist[-1][1], "current_date": hist[-1][0], "actual": actual}
        try:
            jobs[tm] = sc.submit(ts, title="EUR/USD monthly (FRED DEXUSEU, 2000-)",
                                 description=f"EUR/USD monthly average from FRED DEXUSEU, last {LOOKBACK} "
                                             f"months, {HORIZON}-month horizon, walk-forward target {tm}.",
                                 soft_horizon=HORIZON, backtest=True, driver_limit=0)
            log(f"submitted {tm[:7]} (hist -> {hist[-1][0]}, {len(ts)} pts) -> {jobs[tm]}")
        except Exception as e:
            log(f"submit FAILED {tm}: {e}")

    done, pending = set(), set(jobs)
    deadline = time.time() + 35 * 60
    while pending and time.time() < deadline:
        time.sleep(30)
        for tm in list(pending):
            try:
                r = sc.requests.get(f"{config.SYBILION_BASE_URL}/api/v1/forecasts/{jobs[tm]}",
                                    headers=sc.HEADERS, timeout=20).json()
            except Exception:
                continue
            if r.get("status") == "completed":
                done.add(tm); pending.discard(tm); log(f"completed {tm[:7]} ({len(done)}/{len(jobs)})")
            elif r.get("status") == "failed":
                pending.discard(tm); log(f"FAILED {tm}: {r}")
        log(f"... {len(pending)} pending")

    months = []
    for tm in TARGETS:
        if tm not in done:
            continue
        fj = sc.read_artifacts(jobs[tm], "forecast.json")
        pm = {"pair": "EUR/USD", "slug": "eur_usd", "fred_id": "DEXUSEU", "quote": "USD per EUR"}
        d2 = sc._normalize(pm, fj, ctx[tm]["current"])
        scored = score_confidence(d2)              # direction/confidence at the 6-month horizon
        cur, actual = ctx[tm]["current"], ctx[tm]["actual"]
        m1 = d2["forecast"][0]["p50"]              # next-month point (= target month)
        h6 = d2["forecast"][-1]["p50"]             # 6-month-ahead point
        side = "BUY" if scored["direction"] == "UP" else "SELL"
        strength = scored["signal"]                # STRONG / WEAK
        hit_1m = (("UP" if actual > cur else "DOWN") == ("UP" if m1 > cur else "DOWN")) \
            if actual is not None else None
        months.append({
            "month": tm[:7], "call": f"{strength} {side}", "side": side, "strength": strength,
            "confidence": scored["confidence"], "horizon_direction": scored["direction"],
            "current": round(cur, 5), "next_month_p50": round(m1, 5),
            "horizon6_p50": round(h6, 5),
            "actual_next_month": round(actual, 5) if actual is not None else None,
            "next_month_hit": hit_1m,
            "forecast_path": [round(p["p50"], 5) for p in d2["forecast"]],
        })

    scored_1m = [m for m in months if m["next_month_hit"] is not None]
    payload = {"pair": "EUR/USD", "source": "FRED DEXUSEU (monthly avg)", "live": True,
               "horizon_months": HORIZON, "history_basis": f"rolling {LOOKBACK}-month window (5y)",
               "months": months,
               "next_month_hit_rate": round(sum(m["next_month_hit"] for m in scored_1m) / len(scored_1m), 3)
               if scored_1m else None}
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=2)
    log(f"DONE -> {OUT}")
    for m in months:
        h = {True: "HIT", False: "miss", None: "-"}[m["next_month_hit"]]
        log(f"  {m['month']}  {m['call']:11s} conf={m['confidence']:5.1f}  "
            f"cur {m['current']} -> 6mo {m['horizon6_p50']}  (next-mo {m['next_month_p50']} vs "
            f"actual {m['actual_next_month']} {h})")
    log(f"next-month hit-rate {payload['next_month_hit_rate']} over {len(scored_1m)} months")


if __name__ == "__main__":
    main()
