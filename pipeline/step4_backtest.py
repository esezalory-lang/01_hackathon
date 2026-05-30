"""
Layer 4 — Backtest.

Walk-forward validation of a recommended FX trade against the pair's real monthly
history (FRED, 2023->now). At each month we recompute a momentum proxy (price vs
trailing SMA); if it agrees with the trade direction we book P&L, and we track the
cumulative curve versus buy-and-hold.
"""
import config


def load_prices(fred_id):
    """Monthly (dates, prices) for a FRED FX series."""
    import fred_client
    series = fred_client.get_monthly(fred_id)
    return [d for d, _ in series], [v for _, v in series]


def _action_word(strategy):
    action = (strategy.get("action") or "").upper()
    if "SELL" in action or "SHORT" in action:
        return "SELL"
    if "BUY" in action or "LONG" in action:
        return "BUY"
    return "HEDGE"


def backtest_strategy(historical_prices, strategy, lookback_months=18, dates=None):
    """Walk forward; book P&L when momentum matches the trade direction."""
    action = _action_word(strategy)
    # Adapt lookback to short histories so we still produce a curve.
    lookback_months = min(lookback_months, max(3, len(historical_prices) // 2))

    results = []
    for i in range(lookback_months, len(historical_prices)):
        window = historical_prices[i - lookback_months:i]
        current = window[-1]
        sma = sum(window) / len(window)
        signal_up = current > sma

        if action == "SELL" and not signal_up:
            pnl = current - historical_prices[i]    # short profit when price falls
        elif action == "BUY" and signal_up:
            pnl = historical_prices[i] - current     # long profit when price rises
        else:
            pnl = 0.0

        cumulative = sum(r["pnl"] for r in results) + pnl
        results.append({
            "month": i,
            "date": dates[i] if dates else None,
            "price": historical_prices[i],
            "traded": pnl != 0,
            "pnl": round(pnl, 6),
            "cumulative_pnl": round(cumulative, 6),
        })

    traded = sum(1 for r in results if r["traded"])
    wins = sum(1 for r in results if r["pnl"] > 0)
    start = historical_prices[lookback_months] if len(historical_prices) > lookback_months else 0
    buy_hold = [round(r["price"] - start, 6) for r in results]

    return {
        "pair": strategy.get("pair", strategy.get("asset", "")),
        "action": action,
        "lookback_months": lookback_months,
        "trades": results,
        "total_pnl": round(sum(r["pnl"] for r in results), 6),
        "win_rate": round(wins / traded, 3) if traded else 0.0,
        "num_trades": traded,
        "max_drawdown": round(min((r["cumulative_pnl"] for r in results), default=0.0), 6),
        "buy_and_hold_curve": buy_hold,
    }


def run(strategy, pair_meta=None, lookback_months=18, use_mock=None):
    """Backtest a trade. Pulls the pair's FRED series; falls back to mock history."""
    if use_mock is None:
        use_mock = config.USE_MOCK

    fred_id = (pair_meta or {}).get("fred_id")
    pair = (pair_meta or {}).get("pair") or strategy.get("pair")
    if not fred_id and pair in config.PAIR_UNIVERSE:
        fred_id = config.PAIR_UNIVERSE[pair]["fred_id"]

    try:
        dates, prices = load_prices(fred_id)
        if len(prices) < 6:
            raise ValueError("series too short")
    except Exception as e:  # noqa: BLE001 — fall back to mock history offline
        print(f"[step4_backtest] FRED load failed ({e}); using mock history")
        import mock_sybilion
        hist = mock_sybilion._BASE.get(config.pair_slug(pair or ""), {}).get("history", [])
        dates = [h["date"] for h in hist]
        prices = [h["value"] for h in hist]

    return backtest_strategy(prices, strategy, lookback_months=lookback_months, dates=dates)


if __name__ == "__main__":
    import json
    res = run({"pair": "EUR/USD", "action": "SELL EUR/USD forward"})
    print(json.dumps({k: v for k, v in res.items()
                      if k not in ("trades", "buy_and_hold_curve")}, indent=2))
