"""
LIVE Sybilion 6-month forecasts for the World Bank commodity cost-drivers.
Submits all assets in parallel, polls, and writes data/commodities_forecast.json.
"""
import csv
import json
import os
import time

import config
import sybilion_client as sc
from scripts.commodities_fetch import ASSETS, OUT_DIR

HORIZON = 6
OUT = os.path.join(config.DATA_DIR, "commodities_forecast.json")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def _load(slug):
    rows = []
    with open(os.path.join(OUT_DIR, f"{slug}.csv"), newline="") as f:
        for r in csv.DictReader(f):
            rows.append((r["date"], float(r["price"])))
    return rows


def main():
    meta = {a[1]: {"category": a[2], "unit": a[3]} for a in ASSETS}
    jobs, ctx = {}, {}

    # 1) submit
    for _col, slug, cat, unit in ASSETS:
        rows = _load(slug)
        ts = {d: v for d, v in rows}
        ctx[slug] = {"current": rows[-1][1], "current_date": rows[-1][0]}
        try:
            jid = sc.submit(ts, title=f"{slug.replace('_',' ').title()} monthly price ({unit})",
                            description=f"Monthly {slug} price ({unit}) from the World Bank Pink Sheet; "
                                        f"Infineon chip-stack {cat} cost driver.",
                            soft_horizon=HORIZON, backtest=True, driver_limit=0)
            jobs[slug] = jid
            log(f"submitted {slug:16s} -> {jid}")
        except Exception as e:
            log(f"submit FAILED {slug}: {e}")
    log(f"{len(jobs)} jobs submitted; polling...")

    # 2) poll
    done, pending = {}, set(jobs)
    deadline = time.time() + 40 * 60
    while pending and time.time() < deadline:
        time.sleep(30)
        for slug in list(pending):
            try:
                r = sc.requests.get(f"{config.SYBILION_BASE_URL}/api/v1/forecasts/{jobs[slug]}",
                                    headers=sc.HEADERS, timeout=20).json()
            except Exception:
                continue
            if r.get("status") == "completed":
                done[slug] = True
                pending.discard(slug)
                log(f"completed {slug} ({len(done)}/{len(jobs)})")
            elif r.get("status") == "failed":
                pending.discard(slug)
                log(f"FAILED {slug}: {r}")
        log(f"... {len(pending)} pending")

    # 3) read + normalize
    out = {}
    for slug in done:
        try:
            fj = sc.read_artifacts(jobs[slug], "forecast.json")
            mj = None
            try:
                mj = sc.read_artifacts(jobs[slug], "backtest_metrics.json")
            except Exception:
                pass
            pm = {"pair": slug, "slug": slug, "fred_id": None, "quote": meta[slug]["unit"]}
            d2 = sc._normalize(pm, fj, ctx[slug]["current"], mj)
            cur = ctx[slug]["current"]
            last = d2["forecast"][-1]
            out[slug] = {
                "category": meta[slug]["category"], "unit": meta[slug]["unit"],
                "current_price": cur, "current_date": ctx[slug]["current_date"],
                "forecast": d2["forecast"], "backtest": d2["backtest"],
                "horizon_p50": last["p50"],
                "direction": "UP" if last["p50"] > cur else "DOWN",
                "move_pct": round((last["p50"] - cur) / cur * 100, 1) if cur else None,
            }
        except Exception as e:
            log(f"read err {slug}: {e}")

    payload = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "live": True,
               "horizon_months": HORIZON, "assets": out}
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=2)
    log(f"DONE -> {OUT}")
    for slug, a in out.items():
        log(f"  {slug:16s} [{a['category']:9s}] {a['current_price']:>10.2f} -> "
            f"{a['horizon_p50']:>10.2f} ({a['direction']} {a['move_pct']:+}%)  mape={a['backtest'].get('mape')}")


if __name__ == "__main__":
    main()
