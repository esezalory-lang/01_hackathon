"""
hourly_fx.py — refresh the CURRENT month's value from an hourly FX feed.

FRED is daily and lags a day or two, so the latest monthly point can be stale.
This module returns a fresh current-month value:

  1. If TWELVEDATA_API_KEY is set -> pull the 1h FX series for the pair and
     average the bars that fall in the current calendar month.
  2. Otherwise -> fall back to averaging the current month's FRED daily prints
     (still real data, just daily granularity).

Returns (value, source) or (None, None) if nothing is available.
"""
import datetime as dt

import requests

import config

TWELVEDATA_URL = "https://api.twelvedata.com/time_series"


def _current_month_prefix():
    return dt.date.today().strftime("%Y-%m")


def _from_twelvedata(td_symbol):
    if not config.TWELVEDATA_API_KEY:
        return None
    params = {
        "symbol": td_symbol,
        "interval": "1h",
        "outputsize": 800,            # ~1 month of hourly bars
        "apikey": config.TWELVEDATA_API_KEY,
        "format": "JSON",
    }
    r = requests.get(TWELVEDATA_URL, params=params, timeout=30)
    r.raise_for_status()
    body = r.json()
    values = body.get("values")
    if not values:
        return None
    prefix = _current_month_prefix()
    closes = [float(v["close"]) for v in values
              if v.get("datetime", "").startswith(prefix) and v.get("close")]
    if not closes:
        return None
    return round(sum(closes) / len(closes), 4)


def _from_fred_daily(fred_id):
    # Lazy import to avoid a hard dependency cycle.
    import fred_client
    prefix = _current_month_prefix()
    daily = fred_client.get_daily(fred_id, start=f"{prefix}-01")
    closes = [v for d, v in daily if d.startswith(prefix)]
    if not closes:
        return None
    return round(sum(closes) / len(closes), 4)


def get_current_month_value(pair):
    """Return (value, source) for the current month, or (None, None)."""
    meta = config.PAIR_UNIVERSE.get(pair, {})
    try:
        v = _from_twelvedata(meta.get("td_symbol", pair))
        if v is not None:
            return v, "twelvedata_hourly"
    except Exception as e:  # noqa: BLE001
        print(f"[hourly_fx] twelvedata failed for {pair}: {e}")
    try:
        v = _from_fred_daily(meta.get("fred_id"))
        if v is not None:
            return v, "fred_daily_mtd"
    except Exception as e:  # noqa: BLE001
        print(f"[hourly_fx] fred fallback failed for {pair}: {e}")
    return None, None


if __name__ == "__main__":
    for p in config.DEFAULT_PAIRS:
        print(p, get_current_month_value(p))
