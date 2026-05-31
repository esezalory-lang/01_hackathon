"""
Qwen-scoped monthly FX signals (walk-forward) — Infineon treasury.

Pipeline:
  1. Qwen (Featherless) picks the pairs Infineon needs to hedge GIVEN where it
     operates and pays costs  ->  pipeline.step1_scope.scope_pairs_by_operations().
  2. For each picked pair, build a monthly FRED series (cached to data/fx_cache/
     so we don't re-fetch once it's on disk).
  3. Walk forward from Jan-2026 to the latest available month: at each month,
     truncate history to BEFORE that month, Sybilion-forecast the next month
     (horizon 1), score confidence, and classify STRONG/WEAK + BUY/SELL.
  4. Emit the STRONG buys and STRONG sells per month (with the realized value,
     direction hit, and a simple direction P&L) so the call can be backtested.

Output -> data/qwen_monthly_signals.json
"""
import csv
import datetime as dt
import json
import os

import config
import fred_client
from pipeline.step1_scope import scope_pairs_by_operations
from pipeline.step2_forecast import score_confidence

CACHE_DIR = os.path.join(config.DATA_DIR, "fx_cache")


def _provider(use_mock):
    if use_mock:
        import mock_sybilion
        return mock_sybilion
    import sybilion_client
    return sybilion_client


def _cached_series(slug, fred_id, refresh=False):
    """Monthly [(YYYY-MM-01, value)] for a pair. Cached on disk; fetched once."""
    path = os.path.join(CACHE_DIR, f"{slug}.csv")
    if os.path.exists(path) and not refresh:
        rows = list(csv.reader(open(path)))[1:]
        return [(d, float(v)) for d, v in rows if v]
    series = fred_client.get_monthly(fred_id, start=config.BACKTEST_FRED_START)
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "price"])
        w.writerows(series)
    return series


def _meta(p):
    return {"pair": p["pair"], "slug": p["slug"], "fred_id": p["fred_id"], "quote": p["quote"]}


def _forecast_for_month(meta, series, target_month, provider, use_mock, shock):
    """Forecast `meta` for target_month using only history strictly before it."""
    hist = [(d, v) for d, v in series if d < target_month]
    if len(hist) < 40:
        return None  # Sybilion needs >=40 monthly points at horizon 1-3
    actual = next((v for d, v in series if d == target_month), None)
    cur = hist[-1][1]

    raw = provider.forecast_pair(meta, timeseries=dict(hist), current_price=cur,
                                 shock=shock, prefer_series=True,
                                 soft_horizon=config.SOFT_HORIZON_BACKTEST)
    raw.setdefault("pair", meta["pair"])
    raw.setdefault("slug", meta["slug"])
    scored = score_confidence(raw)

    predicted = scored["forecast"][-1]["p50"]
    side = "BUY" if scored["direction"] == "UP" else "SELL"
    realized_dir = hit = pnl_pct = None
    if actual is not None:
        realized_dir = "UP" if actual > cur else "DOWN"
        hit = (realized_dir == scored["direction"])
        move = (actual - cur) / cur * 100 if cur else 0.0
        pnl_pct = round(move if side == "BUY" else -move, 3)  # long if BUY, short if SELL
    return {
        "pair": meta["pair"],
        "slug": meta["slug"],
        "side": side,
        "signal": scored["signal"],
        "confidence": scored["confidence"],
        "direction": scored["direction"],
        "current_price": round(cur, 6),
        "predicted_next_month": round(predicted, 6),
        "actual_next_month": round(actual, 6) if actual is not None else None,
        "realized_direction": realized_dir,
        "direction_hit": hit,
        "pnl_pct": pnl_pct,
    }


def _target_months(built, start="2026-01-01"):
    """Every month present in the data from `start` onward (the walk-forward grid)."""
    all_months = sorted({d for p in built for d, _ in p["series"]})
    return [m for m in all_months if m >= start]


def run_qwen_monthly(use_mock=None, shock=None, start="2026-01-01", refresh=False):
    if use_mock is None:
        use_mock = config.USE_MOCK
    provider = _provider(use_mock)

    scoped = scope_pairs_by_operations()
    built = []
    for p in scoped:
        try:
            series = _cached_series(p["slug"], p["fred_id"], refresh=refresh)
            if len(series) >= 41:
                built.append({**p, "series": series})
            else:
                print(f"[qwen_monthly] {p['pair']}: only {len(series)} pts, skipping")
        except Exception as e:  # noqa: BLE001 — keep the loop alive offline
            print(f"[qwen_monthly] {p['pair']}: series unavailable ({e}); skipping")

    months = _target_months(built, start=start)

    per_month = []
    for tm in months:
        rows = []
        for p in built:
            r = _forecast_for_month(_meta(p), p["series"], tm, provider, use_mock, shock)
            if r:
                rows.append(r)
        # Top 3 BUY + top 3 SELL per month by confidence; each row keeps its
        # STRONG/WEAK label (signal). Full set stays in all_signals.
        def _tag(r):
            return f"{r['pair']}({r['confidence']:.0f}{'*' if r['signal'] == 'STRONG' else ''})"
        buys = sorted([r for r in rows if r["side"] == "BUY"],
                      key=lambda r: r["confidence"], reverse=True)[:3]
        sells = sorted([r for r in rows if r["side"] == "SELL"],
                       key=lambda r: r["confidence"], reverse=True)[:3]
        per_month.append({
            "month": tm[:7],
            "n_pairs_forecast": len(rows),
            "buys": buys,    # top 3 BUY by confidence (STRONG marked with *)
            "sells": sells,  # top 3 SELL by confidence
            "all_signals": sorted(rows, key=lambda r: r["confidence"], reverse=True),
            "headline": (
                f"{tm[:7]}  BUY " + (", ".join(_tag(b) for b in buys) or "—") +
                "  |  SELL " + (", ".join(_tag(s) for s in sells) or "—")
            ),
        })

    # Track record over the surfaced 3+3 board.
    picks = [r for m in per_month for r in (m["buys"] + m["sells"])]
    scored = [r for r in picks if r["direction_hit"] is not None]
    hit_rate = round(sum(r["direction_hit"] for r in scored) / len(scored), 3) if scored else None
    pnl_series = [r["pnl_pct"] for r in picks if r["pnl_pct"] is not None]
    total_pnl = round(sum(pnl_series), 3) if pnl_series else None
    n_strong = sum(1 for r in picks if r["signal"] == "STRONG")

    payload = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "use_mock": use_mock,
        "shock": shock,
        "horizon_months": config.SOFT_HORIZON_BACKTEST,
        "model": config.FEATHERLESS_MODEL,
        "pairs": [{"pair": p["pair"], "slug": p["slug"], "site": p.get("site", ""),
                   "reason": p.get("reason", "")} for p in built],
        "months": per_month,
        "direction_hit_rate": hit_rate,
        "total_pnl_pct": total_pnl,
        "n_picks": len(picks),
        "n_strong": n_strong,
    }
    os.makedirs(config.DATA_DIR, exist_ok=True)
    path = os.path.join(config.DATA_DIR, "qwen_monthly_signals.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    payload["handoff_path"] = path
    return payload


if __name__ == "__main__":
    out = run_qwen_monthly()  # honors USE_MOCK env (set USE_MOCK=0 for the real API)
    print("pairs:", ", ".join(p["pair"] for p in out["pairs"]))
    for m in out["months"]:
        print(" •", m["headline"], f"[{m['n_pairs_forecast']} pairs]")
    print("direction hit-rate:", out["direction_hit_rate"],
          "| total dir-P&L %:", out["total_pnl_pct"],
          "| picks:", out["n_picks"], "| strong:", out["n_strong"])
    print("handoff ->", out["handoff_path"])
