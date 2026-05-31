"""
Donchian channel breakout — monthly, asset-agnostic.

Same breakout logic as the (hourly, FX) pipeline/donchian_backtest.py EA, but for
MONTHLY close-only series (commodities / power), with notional sizing instead of
FX lots. This is the HARDCODED technical strategy we run alongside the Sybilion
forecast-driven backtest so the two can be compared per asset.

Close-only: there are no monthly highs/lows, so high=low=close and the true range
becomes |Δclose|. Donchian channels are rolling max/min of close.
"""

# Monthly parameters (the EA's 20/50 hourly bars don't transfer to monthly).
DC1_PERIOD = 6
DC2_PERIOD = 12
ATR_PERIOD = 6
SL_ATR_MULT = 3.14159      # the same "π stop"
EXIT_TARGET_PCT = 0.90
MAX_BARS_IN_TRADE = 12     # months
RISK_PER_TRADE = 600.0     # notional risk budget per trade (currency of the asset)
STARTING_BALANCE = 100_000.0


def _roll_max(v, i, w): return max(v[i - w + 1:i + 1])
def _roll_min(v, i, w): return min(v[i - w + 1:i + 1])


def run_monthly(prices, dates=None, direction_filter="BOTH"):
    """prices: list[float] monthly closes (chronological). Returns trades/equity/stats."""
    n = len(prices)
    dates = dates or [str(i) for i in range(n)]
    # Indicators (close-only).
    tr = [0.0] * n
    for i in range(1, n):
        tr[i] = abs(prices[i] - prices[i - 1])
    dc1h = [None] * n; dc1l = [None] * n; dc2h = [None] * n; dc2l = [None] * n; atr = [None] * n
    for i in range(n):
        if i >= DC1_PERIOD - 1:
            dc1h[i] = _roll_max(prices, i, DC1_PERIOD); dc1l[i] = _roll_min(prices, i, DC1_PERIOD)
        if i >= DC2_PERIOD - 1:
            dc2h[i] = _roll_max(prices, i, DC2_PERIOD); dc2l[i] = _roll_min(prices, i, DC2_PERIOD)
        if i >= ATR_PERIOD - 1:
            atr[i] = sum(tr[i - ATR_PERIOD + 1:i + 1]) / ATR_PERIOD

    start = DC2_PERIOD - 1  # warmup: widest window
    position = None
    trades = []
    equity = [STARTING_BALANCE]
    counter_buy = counter_sell = 0

    for i in range(start + 1, n):
        price = prices[i]
        # --- exit ---
        if position is not None:
            bars = i - position["entry_idx"]
            exit_price = exit_reason = None
            if position["side"] == "BUY":
                if price <= position["stop"]:
                    exit_price, exit_reason = position["stop"], "stop_loss"
                else:
                    target = position["entry"] + (dc1h[i] - position["entry"]) * EXIT_TARGET_PCT
                    if price >= target:
                        exit_price, exit_reason = target, "target"
            else:
                if price >= position["stop"]:
                    exit_price, exit_reason = position["stop"], "stop_loss"
                else:
                    target = position["entry"] - (position["entry"] - dc1l[i]) * EXIT_TARGET_PCT
                    if price <= target:
                        exit_price, exit_reason = target, "target"
            if exit_price is None and bars >= MAX_BARS_IN_TRADE:
                exit_price, exit_reason = price, "time_stop"
            if exit_price is not None:
                per_unit = (exit_price - position["entry"]) if position["side"] == "BUY" else (position["entry"] - exit_price)
                pnl = per_unit * position["units"]
                trades.append({
                    "entry_idx": position["entry_idx"], "exit_idx": i, "side": position["side"],
                    "entry_price": round(position["entry"], 6), "exit_price": round(exit_price, 6),
                    "units": round(position["units"], 4), "pnl": round(pnl, 2), "exit_reason": exit_reason,
                    "bars_held": bars, "entry_date": dates[position["entry_idx"]], "exit_date": dates[i],
                })
                equity.append(round(equity[-1] + pnl, 2))
                position = None
                continue
        # --- entries ---
        if position is None:
            new1h = dc1h[i] > dc1h[i - 1]; new1l = dc1l[i] < dc1l[i - 1]
            new2h = dc2h[i] > dc2h[i - 1]; new2l = dc2l[i] < dc2l[i - 1]
            counter_sell = min(counter_sell + 1, 2) if (new1h or new2h) else 0
            counter_buy = min(counter_buy + 1, 2) if (new1l or new2l) else 0
            can_sell = direction_filter in ("SELL", "BOTH")
            can_buy = direction_filter in ("BUY", "BOTH")
            if counter_sell >= 2 and can_sell and atr[i] and atr[i] > 0:
                stop = price + SL_ATR_MULT * atr[i]
                position = {"side": "SELL", "entry": price, "stop": stop, "entry_idx": i,
                            "units": RISK_PER_TRADE / (stop - price)}
                counter_sell = 0
            elif counter_buy >= 2 and can_buy and atr[i] and atr[i] > 0:
                stop = price - SL_ATR_MULT * atr[i]
                position = {"side": "BUY", "entry": price, "stop": stop, "entry_idx": i,
                            "units": RISK_PER_TRADE / (price - stop)}
                counter_buy = 0

    wins = [t for t in trades if t["pnl"] > 0]
    total_pnl = sum(t["pnl"] for t in trades)
    bh_pnl = (prices[-1] - prices[start]) / prices[start] * STARTING_BALANCE
    peak = equity[0]; max_dd = 0.0
    for e in equity:
        peak = max(peak, e); max_dd = min(max_dd, e - peak)
    return {
        "trades": trades,
        "equity_curve": [{"idx": i, "balance": e} for i, e in enumerate(equity)],
        "stats": {
            "strategy": "Donchian 6/12 breakout (π-stop)",
            "direction_filter": direction_filter,
            "num_trades": len(trades),
            "win_rate": round(len(wins) / len(trades), 3) if trades else 0.0,
            "total_pnl": round(total_pnl, 2),
            "total_return_pct": round(total_pnl / STARTING_BALANCE * 100, 2),
            "buy_hold_return_pct": round(bh_pnl / STARTING_BALANCE * 100, 2),
            "beats_buy_and_hold": total_pnl > bh_pnl,
            "max_drawdown_pct": round(max_dd / STARTING_BALANCE * 100, 2),
        },
    }
