"""
at_power_h6.py — real Sybilion 6-month forecast for the Austria day-ahead
wholesale electricity price (monthly avg, EUR/MWh).

Reads the monthly history from data/at_ts_payload.json (137 months, 2015->present;
>=60 needed for horizon 6), submits to the REAL Sybilion API at soft_horizon=6 with
backtest and no external drivers, polls, and writes:

  data/at_power_h6.json   history + per-month p05/p10/p50/p90/p95 bands + backtest
  data/at_forecast.csv    tidy forecast table (date, median, IC80, IC90)

Replaces the previous hand-pasted forecast in plot_forecast.py so the run is
reproducible.

Run from repo root (needs SYBILION_API_KEY and network):
    .venv/bin/python -m scripts.at_power_h6
"""
import csv
import datetime as dt
import json
import os

import config
import sybilion_client as sc

PAYLOAD = os.path.join(config.DATA_DIR, "at_ts_payload.json")
OUT_JSON = os.path.join(config.DATA_DIR, "at_power_h6.json")
OUT_CSV = os.path.join(config.DATA_DIR, "at_forecast.csv")
HORIZON = 6


def _q(quantiles, key, default=None):
    for k in (key, key.rstrip("0").rstrip("."), f"{float(key):.2f}"):
        if k in quantiles:
            return quantiles[k]
    return default


def main():
    ts = json.load(open(PAYLOAD))
    dates = sorted(ts)
    current = ts[dates[-1]]
    print(f"submitting {len(ts)} months ({dates[0]} .. {dates[-1]}) at horizon {HORIZON} ...")

    job_id = sc.submit(
        ts,
        title="Austria day-ahead wholesale electricity price — monthly avg (EUR/MWh)",
        description="Monthly average Austrian day-ahead wholesale power price (EUR/MWh); "
                    "Infineon fab energy cost driver.",
        soft_horizon=HORIZON, backtest=True, driver_limit=0,
    )
    print("job:", job_id, "- polling ...")
    sc.poll(job_id)
    fj = sc.read_artifacts(job_id, "forecast.json")
    mj = None
    try:
        mj = sc.read_artifacts(job_id, "backtest_metrics.json")
    except Exception:
        pass

    series = fj.get("data", fj).get("forecast_series", {})
    bands = []
    for i, (date, point) in enumerate(sorted(series.items()), start=1):
        q = point.get("quantile_forecast", {})
        p50 = point.get("forecast", _q(q, "0.50"))
        bands.append({
            "month": i, "date": date,
            "p05": _q(q, "0.05", p50), "p10": _q(q, "0.10", p50), "p50": p50,
            "p90": _q(q, "0.90", p50), "p95": _q(q, "0.95", p50),
        })

    backtest = sc.extract_backtest(mj)

    last = bands[-1]
    out = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "asset": "Austria day-ahead power", "slug": "at_power", "unit": "EUR/MWh",
        "horizon_months": HORIZON, "window_months": len(ts),
        "current_price": current, "current_date": dates[-1],
        "history": [{"date": d, "value": ts[d]} for d in dates],
        "forecast": bands, "backtest": backtest,
        "horizon_p50": last["p50"],
        "direction": "UP" if last["p50"] > current else "DOWN",
        "move_pct": round((last["p50"] - current) / current * 100, 1) if current else None,
        "source": "sybilion",
    }
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(out, f, indent=2)

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "forecast_eur_mwh", "ic80_low", "ic80_high", "ic90_low", "ic90_high"])
        for b in bands:
            w.writerow([b["date"], round(b["p50"], 2), round(b["p10"], 2), round(b["p90"], 2),
                        round(b["p05"], 2), round(b["p95"], 2)])

    print(f"current: {current} ({dates[-1]}) | mape: {backtest.get('mape')}")
    for b in bands:
        print(f"  {b['date']}  p50={b['p50']:.2f}  IC80=[{b['p10']:.2f},{b['p90']:.2f}]")
    print(f"{out['direction']} {out['move_pct']:+}% over {HORIZON}m")
    print("saved", OUT_JSON, "and", OUT_CSV)


if __name__ == "__main__":
    main()
