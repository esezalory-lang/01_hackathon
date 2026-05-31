"""
asset_backtests.py — the EUR/USD backtest treatment, applied to the non-FX
cost drivers: copper, TTF gas (Europe), and Austria day-ahead power.

Runs BOTH backtests we built for EUR/USD:

  A) P&L walk-forward vs buy-and-hold  (pipeline.step4_backtest.backtest_strategy)
     Turn each asset's 6-month forecast into a BUY/SELL trade, then walk its real
     monthly history booking P&L with the SMA-momentum filter, vs buy-and-hold.
     No Sybilion calls.

  B) Live Sybilion direction track-record  (cf. scripts.live_eurusd_fred_loop)
     For each of the last 5 available months: feed history up to the prior month,
     forecast 6 months ahead, derive STRONG/WEAK BUY/SELL + confidence, and score
     the next-month direction vs the realized price. Hits Sybilion (5 jobs/asset).

Writes data/asset_backtests.json.

Run from repo root (needs SYBILION_API_KEY + network for part B):
    .venv/bin/python -m scripts.asset_backtests
"""
import csv
import json
import os
import time

import config
import sybilion_client as sc
from pipeline.step2_forecast import score_confidence
from pipeline.step4_backtest import backtest_strategy

HORIZON = 6
LOOKBACK = 84          # match the EUR/USD loop (72 for horizon-6 + ~12m hindcast holdout)
N_TARGETS = 5          # last 5 available months, like EUR/USD's Jan..May 2026
OUT = os.path.join(config.DATA_DIR, "asset_backtests.json")

# (slug, display name, unit, series source). Directions come from the live h6 forecasts.
ASSETS = [
    {"slug": "copper", "name": "Copper", "unit": "USD/mt",
     "csv": os.path.join(config.DATA_DIR, "commodities", "copper.csv")},
    {"slug": "ttf_gas_europe", "name": "TTF Gas (Europe)", "unit": "USD/mmbtu",
     "csv": os.path.join(config.DATA_DIR, "commodities", "ttf_gas_europe.csv")},
    {"slug": "at_power", "name": "Austria day-ahead power", "unit": "EUR/MWh",
     "payload": os.path.join(config.DATA_DIR, "at_ts_payload.json")},
]


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def load_series(a):
    """-> [(date, price)] monthly, ascending."""
    if a.get("csv"):
        rows = []
        with open(a["csv"], newline="") as f:
            for r in csv.DictReader(f):
                rows.append((r["date"], float(r["price"])))
        return rows
    ts = json.load(open(a["payload"]))
    return [(d, ts[d]) for d in sorted(ts)]


def forecast_direction(a):
    """Read the asset's already-computed 6-month forecast (current, horizon p50, dir)."""
    if a["slug"] == "at_power":
        d = json.load(open(os.path.join(config.DATA_DIR, "at_power_h6.json")))
        return d["current_price"], d["horizon_p50"], d["direction"]
    d = json.load(open(os.path.join(config.DATA_DIR, "commodities_forecast.json")))["assets"][a["slug"]]
    return d["current_price"], d["horizon_p50"], d["direction"]


# --------------------------------------------------------------------------
# A) P&L walk-forward vs buy-and-hold  (no API)
# --------------------------------------------------------------------------
def pnl_backtest(a, series):
    cur, h6, direction = forecast_direction(a)
    action = f"SELL {a['name']}" if direction == "DOWN" else f"BUY {a['name']}"
    dates = [d for d, _ in series]
    prices = [v for _, v in series]
    res = backtest_strategy(prices, {"asset": a["name"], "action": action},
                            lookback_months=18, dates=dates)
    final_bh = res["buy_and_hold_curve"][-1] if res["buy_and_hold_curve"] else 0.0
    return {
        "action": action, "forecast_direction": direction,
        "current_price": cur, "horizon6_p50": h6,
        "lookback_months": res["lookback_months"],
        "num_trades": res["num_trades"], "win_rate": res["win_rate"],
        "total_pnl": res["total_pnl"], "max_drawdown": res["max_drawdown"],
        "buy_and_hold_final": round(final_bh, 4),
        "beats_buy_and_hold": res["total_pnl"] > final_bh,
        "units": a["unit"],
    }


# --------------------------------------------------------------------------
# B) Live Sybilion direction track-record  (mirrors live_eurusd_fred_loop)
# --------------------------------------------------------------------------
def submit_walkforward(a, series):
    """Submit one job per target month; return {target: (job_id, ctx)}."""
    targets = [d for d, _ in series][-N_TARGETS:]
    jobs = {}
    for tm in targets:
        hist = [(d, v) for d, v in series if d < tm][-LOOKBACK:]
        if len(hist) < 60:
            log(f"  {a['slug']} {tm}: only {len(hist)} pts history, skipping")
            continue
        actual = next((v for d, v in series if d == tm), None)
        ts = {d: v for d, v in hist}
        try:
            jid = sc.submit(ts, title=f"{a['name']} monthly ({a['unit']})",
                            description=f"{a['name']} monthly series, last {len(ts)} months, "
                                        f"{HORIZON}-month horizon, walk-forward target {tm}.",
                            soft_horizon=HORIZON, backtest=True, driver_limit=0)
            jobs[tm] = {"job_id": jid, "current": hist[-1][1], "current_date": hist[-1][0],
                        "actual": actual}
            log(f"  submitted {a['slug']:16s} {tm} (hist->{hist[-1][0]}, {len(ts)}pts) -> {jid}")
        except Exception as e:
            log(f"  submit FAILED {a['slug']} {tm}: {e}")
    return jobs


def score_walkforward(a, jobs):
    months = []
    for tm, c in jobs.items():
        try:
            fj = sc.read_artifacts(c["job_id"], "forecast.json")
        except Exception as e:
            log(f"  read err {a['slug']} {tm}: {e}")
            continue
        pm = {"pair": a["name"], "slug": a["slug"], "fred_id": None, "quote": a["unit"]}
        d2 = sc._normalize(pm, fj, c["current"])          # no metrics -> neutral accuracy (as EUR/USD loop)
        scored = score_confidence(d2)
        cur, actual = c["current"], c["actual"]
        m1 = d2["forecast"][0]["p50"]
        h6 = d2["forecast"][-1]["p50"]
        side = "BUY" if scored["direction"] == "UP" else "SELL"
        hit_1m = (("UP" if actual > cur else "DOWN") == ("UP" if m1 > cur else "DOWN")) \
            if actual is not None else None
        months.append({
            "month": tm[:7], "call": f"{scored['signal']} {side}", "side": side,
            "strength": scored["signal"], "confidence": scored["confidence"],
            "horizon_direction": scored["direction"], "current": round(cur, 5),
            "next_month_p50": round(m1, 5), "horizon6_p50": round(h6, 5),
            "actual_next_month": round(actual, 5) if actual is not None else None,
            "next_month_hit": hit_1m,
        })
    scored_1m = [m for m in months if m["next_month_hit"] is not None]
    return {
        "months": months,
        "next_month_hit_rate": round(sum(m["next_month_hit"] for m in scored_1m) / len(scored_1m), 3)
        if scored_1m else None,
    }


def main():
    series_by = {a["slug"]: load_series(a) for a in ASSETS}

    # A) P&L backtests (instant)
    pnl = {}
    for a in ASSETS:
        pnl[a["slug"]] = pnl_backtest(a, series_by[a["slug"]])
        r = pnl[a["slug"]]
        log(f"PnL {a['slug']:16s} {r['action']:22s} trades={r['num_trades']:2d} "
            f"win={r['win_rate']:.0%} pnl={r['total_pnl']:.4f} bh={r['buy_and_hold_final']:.4f} "
            f"{'BEATS' if r['beats_buy_and_hold'] else 'trails'} b&h")

    # B) live walk-forward — submit all assets in parallel, then poll
    all_jobs = {a["slug"]: submit_walkforward(a, series_by[a["slug"]]) for a in ASSETS}
    pending = {(s, tm) for s, jobs in all_jobs.items() for tm in jobs}
    log(f"{len(pending)} walk-forward jobs submitted; polling...")
    deadline = time.time() + 35 * 60
    done = set()
    while pending and time.time() < deadline:
        time.sleep(30)
        for s, tm in list(pending):
            jid = all_jobs[s][tm]["job_id"]
            try:
                r = sc.requests.get(f"{config.SYBILION_BASE_URL}/api/v1/forecasts/{jid}",
                                    headers=sc.HEADERS, timeout=20).json()
            except Exception:
                continue
            if r.get("status") == "completed":
                done.add((s, tm)); pending.discard((s, tm))
            elif r.get("status") == "failed":
                pending.discard((s, tm)); log(f"  FAILED {s} {tm}")
        log(f"... {len(pending)} pending ({len(done)} done)")

    live = {a["slug"]: score_walkforward(a, all_jobs[a["slug"]]) for a in ASSETS}

    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "live": True,
           "horizon_months": HORIZON, "history_basis": f"rolling {LOOKBACK}-month window",
           "assets": {}}
    for a in ASSETS:
        out["assets"][a["slug"]] = {
            "name": a["name"], "unit": a["unit"],
            "pnl_backtest": pnl[a["slug"]],
            "live_walkforward": live[a["slug"]],
        }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)
    log(f"DONE -> {OUT}")
    for a in ASSETS:
        lw = live[a["slug"]]
        log(f"  {a['slug']:16s} hit-rate {lw['next_month_hit_rate']} over "
            f"{len([m for m in lw['months'] if m['next_month_hit'] is not None])} months")


if __name__ == "__main__":
    main()
