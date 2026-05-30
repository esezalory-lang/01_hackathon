"""
fred_client.py — monthly FX history from FRED.

FRED's FX series (DEX*) are DAILY. We pull the daily CSV (keyless fredgraph
endpoint, no API key needed) from FRED_START and resample to a monthly mean,
month-aligned to YYYY-MM-01 — the shape Sybilion wants.
"""
import csv
import io
from collections import defaultdict

import requests

import config

FREDGRAPH = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def get_daily(fred_id, start=None):
    """Return [(YYYY-MM-DD, float)] daily observations, missing values dropped."""
    start = start or config.FRED_START
    r = requests.get(FREDGRAPH, params={"id": fred_id, "cosd": start}, timeout=30)
    r.raise_for_status()
    out = []
    reader = csv.reader(io.StringIO(r.text))
    next(reader, None)  # header: observation_date,<ID>
    for row in reader:
        if len(row) < 2:
            continue
        date, val = row[0], row[1]
        if val in (".", "", "NA"):  # FRED marks gaps with "."
            continue
        try:
            out.append((date, float(val)))
        except ValueError:
            continue
    return out


def get_monthly(fred_id, start=None):
    """Daily -> monthly mean. Returns [(YYYY-MM-01, rounded_value)] chronological."""
    buckets = defaultdict(list)
    for date, val in get_daily(fred_id, start=start):
        buckets[date[:7]].append(val)          # group by 'YYYY-MM'
    months = sorted(buckets)
    return [(f"{m}-01", round(sum(buckets[m]) / len(buckets[m]), 4))
            for m in months if buckets[m]]


if __name__ == "__main__":
    series = get_monthly("DEXUSEU")
    print(f"DEXUSEU monthly points: {len(series)}  {series[0]} ... {series[-1]}")
