"""
Per-asset backtest comparison: HARDCODED Donchian vs SYBILION forecast-driven.

For copper / TTF gas / AT power we run, on the real monthly series:
  1. donchian              — the hardcoded technical strategy (no forecast input)
  2. donchian_with_sybilion — the SAME strategy, but only taking trades on the side
                              the Sybilion forecast points (its directional filter)
  3. sybilion              — the forecast-driven momentum backtest (from
                              data/asset_backtests.json, generated earlier)

Writes data/strategy_backtests.json so the hardcoded and Sybilion strategies sit
side by side and can be compared (does the forecast beat a naive rule?).
"""
import csv
import datetime as dt
import json
import os

import config
from pipeline.donchian_monthly import run_monthly

COMMODITIES_DIR = os.path.join(config.DATA_DIR, "commodities")

ASSETS = {
    "Copper":  {"unit": "USD/mt", "csv": "copper.csv", "sybilion_key": "copper"},
    "TTF Gas": {"unit": "USD/mmbtu", "csv": "ttf_gas_europe.csv", "sybilion_key": "ttf_gas_europe"},
    "AT Power": {"unit": "EUR/MWh", "csv": None, "sybilion_key": "at_power"},  # from at_power_h6.json
}


def _load_csv(path):
    rows = list(csv.reader(open(path)))[1:]
    dates = [r[0][:7] for r in rows if r and r[1]]
    prices = [float(r[1]) for r in rows if r and r[1]]
    return dates, prices


def _load_at_power():
    d = json.load(open(os.path.join(config.DATA_DIR, "at_power_h6.json")))
    return [h["date"][:7] for h in d["history"]], [float(h["value"]) for h in d["history"]]


def _sybilion_summary():
    path = os.path.join(config.DATA_DIR, "asset_backtests.json")
    if not os.path.exists(path):
        return {}
    return json.load(open(path)).get("assets", {})


def run():
    syb = _sybilion_summary()
    out = {}
    for name, meta in ASSETS.items():
        if meta["csv"]:
            dates, prices = _load_csv(os.path.join(COMMODITIES_DIR, meta["csv"]))
        else:
            dates, prices = _load_at_power()

        sk = syb.get(meta["sybilion_key"], {})
        pnl = sk.get("pnl_backtest", {})
        fdir = pnl.get("forecast_direction")               # "UP" / "DOWN"
        side = "BUY" if fdir == "UP" else "SELL" if fdir == "DOWN" else "BOTH"

        donchian = run_monthly(prices, dates, direction_filter="BOTH")
        filtered = run_monthly(prices, dates, direction_filter=side)

        out[name] = {
            "name": name, "unit": meta["unit"], "months": len(prices),
            "forecast_direction": fdir,
            "donchian": donchian,                            # hardcoded technical
            "donchian_with_sybilion": filtered,              # hardcoded + forecast filter
            "sybilion": {                                    # forecast-driven momentum (existing)
                "action": pnl.get("action"),
                "num_trades": pnl.get("num_trades"),
                "win_rate": pnl.get("win_rate"),
                "total_pnl": pnl.get("total_pnl"),
                "max_drawdown": pnl.get("max_drawdown"),
                "beats_buy_and_hold": pnl.get("beats_buy_and_hold"),
                "next_month_hit_rate": sk.get("live_walkforward", {}).get("next_month_hit_rate"),
                "units": pnl.get("units"),
            },
        }
    payload = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "note": "Hardcoded Donchian (monthly) vs Sybilion forecast-driven backtest, per asset.",
        "assets": out,
    }
    path = os.path.join(config.DATA_DIR, "strategy_backtests.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    payload["handoff_path"] = path
    return payload


if __name__ == "__main__":
    p = run()
    hdr = f"{'asset':9s} {'donchian':>18s} {'+sybilion filter':>18s} {'sybilion mom.':>16s} {'buy&hold':>10s}"
    print(hdr); print("-" * len(hdr))
    for name, a in p["assets"].items():
        d = a["donchian"]["stats"]; f = a["donchian_with_sybilion"]["stats"]; s = a["sybilion"]
        print(f"{name:9s} "
              f"{d['total_return_pct']:>7.1f}% ({d['num_trades']:>2d}t,{d['win_rate']*100:>3.0f}%) "
              f"{f['total_return_pct']:>7.1f}% ({f['num_trades']:>2d}t,{f['win_rate']*100:>3.0f}%) "
              f"{str(s['total_pnl']):>10s} {s['action'] or '-':>5s} "
              f"{d['buy_hold_return_pct']:>8.1f}%")
    print("->", p["handoff_path"])
