"""
eur_usd_h6.py — real Sybilion 6-month forecast for EUR/USD from 84 months of FRED.

Pulls DEXUSEU monthly history, takes the last 84 points (>=60 needed for horizon 6),
submits to the REAL Sybilion API at soft_horizon=6, and saves the history + per-month
p10/p50/p90 bands to data/eur_usd_h6.json for the UI chart.

Run locally (needs SYBILION_API_KEY and network):
    .venv/bin/python eur_usd_h6.py
"""
import datetime as dt
import json
import os

import config
import fred_client
import sybilion_client

WINDOW = 84  # months of history to submit


def main():
    series = fred_client.get_monthly("DEXUSEU", start="2018-12-01")
    series = series[-WINDOW:]
    ts = {d: v for d, v in series}
    meta = {"pair": "EUR/USD", "slug": "eur_usd", "fred_id": "DEXUSEU", "quote": "USD per EUR"}
    print(f"submitting {len(ts)} months ({series[0][0]} .. {series[-1][0]}) at horizon 6 ...")

    res = sybilion_client.forecast_pair(meta, ts, soft_horizon=6)

    out = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "pair": "EUR/USD",
        "fred_id": "DEXUSEU",
        "horizon_months": 6,
        "window_months": len(ts),
        "current_price": res["current_price"],
        "history": [{"date": d, "value": v} for d, v in series],
        "forecast": res["forecast"],          # [{month, p10, p50, p90}]
        "backtest": res.get("backtest", {}),
        "source": res.get("source"),
    }
    os.makedirs(config.DATA_DIR, exist_ok=True)
    path = os.path.join(config.DATA_DIR, "eur_usd_h6.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)

    print("current:", out["current_price"], "| mape:", out["backtest"].get("mape"))
    for b in res["forecast"]:
        print(b)
    print("saved", path)


if __name__ == "__main__":
    main()
