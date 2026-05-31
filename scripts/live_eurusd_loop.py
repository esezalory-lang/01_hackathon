"""
LIVE Sybilion walk-forward on the user-supplied EUR/USD monthly file
(MetaTrader OHLC, 2000-01 -> 2026-02). Month-end CLOSE is the price.

For each target month from Jan 2026 to the first month past the data:
  - feed ALL history up to the prior month to Sybilion (horizon 1, limit 0),
  - emit a STRONG/weak BUY or SELL for that month,
  - score against the realized close when available.

Writes data/eurusd_loop_live.json.
"""
import csv
import datetime as dt
import json
import os
import time

import config
import sybilion_client as sc
from pipeline.step2_forecast import score_confidence

SRC = os.path.join(config.DATA_DIR, "EURUSD_Monthly_200001010000_202602010000.csv")
OUT = os.path.join(config.DATA_DIR, "eurusd_loop_live.json")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def load_series():
    """Return [(YYYY-MM-01, close)] from the MetaTrader monthly file."""
    rows = []
    with open(SRC, newline="") as f:
        r = csv.reader(f, delimiter="\t")
        next(r, None)  # header
        for row in r:
            if not row or not row[0]:
                continue
            d = row[0].replace(".", "-")          # 2000.01.01 -> 2000-01-01
            rows.append((d, float(row[4])))        # <CLOSE>
    return rows


def _next_month(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y + 1:04d}-01-01" if m == 12 else f"{y:04d}-{m + 1:02d}-01"


def main():
    series = load_series()
    last_date = series[-1][0]
    # Targets: Jan 2026 .. (month after last data point).
    targets = []
    t = "2026-01-01"
    end = _next_month(last_date[:7])
    while t <= end:
        targets.append(t)
        t = _next_month(t[:7])
    log(f"loaded {len(series)} pts ({series[0][0]}..{last_date}); targets {[x[:7] for x in targets]}")

    # 1) submit (full history < target each time)
    jobs, ctx = {}, {}
    for tm in targets:
        hist = [(d, v) for d, v in series if d < tm]
        actual = next((v for d, v in series if d == tm), None)
        ts = {d: v for d, v in hist}
        ctx[tm] = {"current": hist[-1][1], "current_date": hist[-1][0], "actual": actual}
        try:
            jobs[tm] = sc.submit(ts, title="EUR/USD monthly close (user MT5 data, 2000-)",
                                 description="EUR/USD month-end close, full history, walk-forward target "
                                             f"{tm}.",
                                 soft_horizon=1, backtest=True, driver_limit=0)
            log(f"submitted {tm[:7]} (hist -> {hist[-1][0]}, {len(ts)} pts) -> {jobs[tm]}")
        except Exception as e:
            log(f"submit FAILED {tm}: {e}")

    # 2) poll
    done, pending = set(), set(jobs)
    deadline = time.time() + 30 * 60
    while pending and time.time() < deadline:
        time.sleep(30)
        for tm in list(pending):
            try:
                r = sc.requests.get(f"{config.SYBILION_BASE_URL}/api/v1/forecasts/{jobs[tm]}",
                                    headers=sc.HEADERS, timeout=20).json()
            except Exception:
                continue
            if r.get("status") == "completed":
                done.add(tm); pending.discard(tm)
                log(f"completed {tm[:7]} ({len(done)}/{len(jobs)})")
            elif r.get("status") == "failed":
                pending.discard(tm); log(f"FAILED {tm}: {r}")
        log(f"... {len(pending)} pending")

    # 3) read + score
    months = []
    for tm in targets:
        if tm not in done:
            continue
        fj = sc.read_artifacts(jobs[tm], "forecast.json")
        pm = {"pair": "EUR/USD", "slug": "eur_usd", "fred_id": None, "quote": "USD per EUR"}
        d2 = sc._normalize(pm, fj, ctx[tm]["current"])
        scored = score_confidence(d2)
        cur, actual = ctx[tm]["current"], ctx[tm]["actual"]
        pred = scored["forecast"][-1]["p50"]
        side = "BUY" if scored["direction"] == "UP" else "SELL"
        strength = "STRONG" if scored["signal"] == "STRONG" else "WEAK"
        hit = (("UP" if actual > cur else "DOWN") == scored["direction"]) if actual is not None else None
        months.append({
            "month": tm[:7], "call": f"{strength} {side}", "side": side, "strength": strength,
            "confidence": scored["confidence"], "current_close": round(cur, 5),
            "predicted_close": round(pred, 5),
            "actual_close": round(actual, 5) if actual is not None else None,
            "direction_hit": hit,
        })

    scored_hits = [m for m in months if m["direction_hit"] is not None]
    payload = {"pair": "EUR/USD", "source": "user MT5 monthly (2000-2026.02)", "live": True,
               "horizon_months": 1, "history_basis": "all historical, month-end close",
               "months": months,
               "direction_hit_rate": round(sum(m["direction_hit"] for m in scored_hits) / len(scored_hits), 3)
               if scored_hits else None}
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=2)
    log(f"DONE -> {OUT}")
    for m in months:
        a = f"actual {m['actual_close']}" if m["actual_close"] is not None else "actual n/a (forward call)"
        h = {True: "HIT", False: "miss", None: "-"}[m["direction_hit"]]
        log(f"  {m['month']}  {m['call']:11s} conf={m['confidence']:5.1f}  "
            f"cur {m['current_close']} -> pred {m['predicted_close']}  {a}  {h}")
    log(f"hit-rate {payload['direction_hit_rate']} over {len(scored_hits)} scored months")


if __name__ == "__main__":
    main()
