"""
pairs28.py — build the 28 major FX pairs as monthly series from FRED.

The 8 majors (USD, EUR, JPY, GBP, CHF, CAD, AUD, NZD) form C(8,2)=28 pairs, all
derivable from 7 FRED USD-leg series. We express every currency as USD-per-unit,
then quote each pair BASE/QUOTE in the conventional direction:

    price(BASE/QUOTE) = (USD per BASE) / (USD per QUOTE)

Base/quote follow config.MAJORS_PRECEDENCE (EUR>GBP>AUD>NZD>USD>CAD>CHF>JPY).
"""
from itertools import combinations

import config


def _usd_per_currency_monthly(start=None):
    """Return {currency: {YYYY-MM-01: usd_per_unit}} for all 8 majors."""
    import fred_client

    usd_per = {"USD": None}  # USD filled per-month as 1.0 against any month set
    months_seen = set()
    for cur, (fred_id, invert) in config.MAJOR_USD_LEGS.items():
        series = dict(fred_client.get_monthly(fred_id, start=start))
        if invert:
            series = {m: (1.0 / v) for m, v in series.items() if v}
        usd_per[cur] = series
        months_seen |= set(series)

    usd_per["USD"] = {m: 1.0 for m in months_seen}
    return usd_per


def build_all(start=None):
    """Return {pair: {slug, base, quote, series:[(month,rate)], current_price}}.

    `start` overrides config.FRED_START (the walk-forward backtest needs earlier
    history so each truncated window still clears Sybilion's 40-point minimum).
    """
    usd_per = _usd_per_currency_monthly(start=start)
    rank = {c: i for i, c in enumerate(config.MAJORS_PRECEDENCE)}

    out = {}
    for a, b in combinations(config.MAJORS_PRECEDENCE, 2):
        base, quote = (a, b) if rank[a] < rank[b] else (b, a)
        pa, pb = usd_per[base], usd_per[quote]
        months = sorted(set(pa) & set(pb))
        series = [(m, round(pa[m] / pb[m], 6)) for m in months if pb[m]]
        if not series:
            continue
        pair = f"{base}/{quote}"
        out[pair] = {
            "pair": pair,
            "slug": config.pair_slug(pair),
            "base": base,
            "quote": quote,
            "series": series,
            "current_price": series[-1][1],
        }
    return out


def pair_meta(pair, info):
    """Lightweight meta dict for the forecast providers."""
    return {
        "pair": pair,
        "slug": info["slug"],
        "fred_id": None,            # derived cross, no single FRED id
        "quote": f"{info['quote']} per {info['base']}",
    }


if __name__ == "__main__":
    allp = build_all()
    print(f"built {len(allp)} pairs")
    for p, info in list(allp.items()):
        s = info["series"]
        print(f"  {p:9s} pts={len(s):3d}  {s[0][0]}->{s[-1][0]}  last={s[-1][1]}")
