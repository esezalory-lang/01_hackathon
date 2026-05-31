"""
Donchian Channel breakout backtester for EUR/USD.
Ported from MQL5 EA. Filtered by Sybilion direction.
"""
import pandas as pd
import numpy as np
from typing import Literal

# Strategy parameters (from the original EA)
DC1_PERIOD = 20
DC2_PERIOD = 50
ATR_PERIOD = 20
SL_ATR_MULT = 3.14159     # The famous "π stop"
EXIT_TARGET_PCT = 0.90    # Exit at 90% of the way to opposite DC
MAX_BARS_IN_TRADE = 80    # Time stop
RISK_PER_TRADE_USD = 600  # Fixed dollar risk


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add DC1, DC2, ATR columns. df must have high, low, close."""
    df = df.copy()

    # Donchian Channel 1 (20 periods)
    df["dc1_high"] = df["high"].rolling(DC1_PERIOD).max()
    df["dc1_low"]  = df["low"].rolling(DC1_PERIOD).min()
    df["dc1_mid"]  = (df["dc1_high"] + df["dc1_low"]) / 2

    # Donchian Channel 2 (50 periods)
    df["dc2_high"] = df["high"].rolling(DC2_PERIOD).max()
    df["dc2_low"]  = df["low"].rolling(DC2_PERIOD).min()
    df["dc2_mid"]  = (df["dc2_high"] + df["dc2_low"]) / 2

    # ATR
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close  = (df["low"]  - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.rolling(ATR_PERIOD).mean()

    return df


def run_backtest(
    df: pd.DataFrame,
    direction_filter: Literal["BUY", "SELL", "BOTH"] = "BOTH",
    starting_balance: float = 100_000.0
):
    """
    Walk forward through the price data, running Donchian breakout logic.
    Returns trades, equity curve, and stats.

    direction_filter: if "SELL" (from a Sybilion SELL signal), only take
    sell breakouts. If "BUY", only buys. "BOTH" means no filter.
    """
    df = compute_indicators(df).dropna().reset_index(drop=True)

    position = None       # dict with: side, entry_price, stop, entry_idx, lots
    trades = []
    equity = [starting_balance]
    counter_buy = 0       # state machine for buy confirmation
    counter_sell = 0      # state machine for sell confirmation

    for i in range(1, len(df)):
        row, prev = df.iloc[i], df.iloc[i - 1]
        price = row["close"]

        # --- Check exit first if in position ---
        if position is not None:
            bars_held = i - position["entry_idx"]
            exit_reason = None
            exit_price = None

            if position["side"] == "BUY":
                # Stop loss
                if row["low"] <= position["stop"]:
                    exit_price = position["stop"]
                    exit_reason = "stop_loss"
                # Take profit at 90% toward opposite DC1
                else:
                    target = position["entry_price"] + (row["dc1_high"] - position["entry_price"]) * EXIT_TARGET_PCT
                    if row["high"] >= target:
                        exit_price = target
                        exit_reason = "target"
            else:  # SELL
                if row["high"] >= position["stop"]:
                    exit_price = position["stop"]
                    exit_reason = "stop_loss"
                else:
                    target = position["entry_price"] - (position["entry_price"] - row["dc1_low"]) * EXIT_TARGET_PCT
                    if row["low"] <= target:
                        exit_price = target
                        exit_reason = "target"

            # Time stop
            if exit_price is None and bars_held >= MAX_BARS_IN_TRADE:
                exit_price = price
                exit_reason = "time_stop"

            if exit_price is not None:
                pnl_per_unit = (exit_price - position["entry_price"]) if position["side"] == "BUY" else (position["entry_price"] - exit_price)
                pnl = pnl_per_unit * position["lots"] * 100_000  # standard FX lot
                trades.append({
                    "entry_idx": position["entry_idx"],
                    "exit_idx": i,
                    "side": position["side"],
                    "entry_price": position["entry_price"],
                    "exit_price": exit_price,
                    "stop": position["stop"],
                    "lots": position["lots"],
                    "pnl": pnl,
                    "exit_reason": exit_reason,
                    "bars_held": bars_held,
                    "entry_date": str(df.iloc[position["entry_idx"]].get("date", position["entry_idx"])),
                    "exit_date": str(row.get("date", i)),
                })
                equity.append(equity[-1] + pnl)
                position = None
                continue

        # --- No position: check for entry signals ---
        if position is None:
            # Donchian breakout detection
            new_dc1_high = row["dc1_high"] > prev["dc1_high"]
            new_dc1_low  = row["dc1_low"]  < prev["dc1_low"]
            new_dc2_high = row["dc2_high"] > prev["dc2_high"]
            new_dc2_low  = row["dc2_low"]  < prev["dc2_low"]

            # SELL setup = new high (price broke up — fade it)
            if new_dc1_high or new_dc2_high:
                counter_sell = min(counter_sell + 1, 2)
            else:
                counter_sell = 0

            # BUY setup = new low (price broke down — fade it)
            if new_dc1_low or new_dc2_low:
                counter_buy = min(counter_buy + 1, 2)
            else:
                counter_buy = 0

            # Apply Sybilion direction filter
            can_sell = direction_filter in ("SELL", "BOTH")
            can_buy  = direction_filter in ("BUY",  "BOTH")

            # Enter SELL when counter reaches 2 (confirmed)
            if counter_sell >= 2 and can_sell and row["atr"] > 0:
                entry = price
                stop = entry + SL_ATR_MULT * row["atr"]
                stop_distance = stop - entry
                lots = RISK_PER_TRADE_USD / (stop_distance * 100_000)  # rough FX sizing
                position = {"side": "SELL", "entry_price": entry, "stop": stop, "entry_idx": i, "lots": round(lots, 2)}
                counter_sell = 0

            # Enter BUY when counter reaches 2
            elif counter_buy >= 2 and can_buy and row["atr"] > 0:
                entry = price
                stop = entry - SL_ATR_MULT * row["atr"]
                stop_distance = entry - stop
                lots = RISK_PER_TRADE_USD / (stop_distance * 100_000)
                position = {"side": "BUY", "entry_price": entry, "stop": stop, "entry_idx": i, "lots": round(lots, 2)}
                counter_buy = 0

    # Stats
    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    total_pnl = sum(t["pnl"] for t in trades)

    # Buy and hold comparison (entry at first bar, exit at last bar, $100k notional)
    bh_pnl = (df.iloc[-1]["close"] - df.iloc[0]["close"]) / df.iloc[0]["close"] * starting_balance

    # Max drawdown
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        peak = max(peak, e)
        max_dd = min(max_dd, e - peak)

    return {
        "trades": trades,
        "equity_curve": [{"idx": i, "balance": round(e, 2)} for i, e in enumerate(equity)],
        "stats": {
            "num_trades": n,
            "win_rate": round(len(wins) / n, 3) if n > 0 else 0,
            "total_pnl_usd": round(total_pnl, 2),
            "total_return_pct": round(total_pnl / starting_balance * 100, 2),
            "buy_hold_pnl_usd": round(bh_pnl, 2),
            "buy_hold_return_pct": round(bh_pnl / starting_balance * 100, 2),
            "max_drawdown_usd": round(max_dd, 2),
            "avg_win_usd": round(sum(t["pnl"] for t in wins) / len(wins), 2) if wins else 0,
            "avg_loss_usd": round(sum(t["pnl"] for t in losses) / len(losses), 2) if losses else 0,
            "direction_filter": direction_filter,
        }
    }
