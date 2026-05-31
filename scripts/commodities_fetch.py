"""
commodities_fetch.py — real monthly Infineon cost-driver series from the
World Bank "Pink Sheet" (free, monthly, decades). One download covers the gas
and packaging/precious-metal categories of the chip cost stack.

Writes data/commodities/<slug>.csv (date,price) from START_YEAR onward.
"""
import csv
import os

import openpyxl
import requests

import config

PINK_URL = ("https://thedocs.worldbank.org/en/doc/"
            "18675f1d1639c7a34d463f59263ba0a2-0050012025/related/"
            "CMO-Historical-Data-Monthly.xlsx")
LOCAL_XLSX = "/tmp/wb_pink.xlsx"
START_YEAR = 2015  # long history -> enables a 6-month Sybilion horizon (>=60 pts)
OUT_DIR = os.path.join(config.DATA_DIR, "commodities")

# Infineon chip-stack assets available in the Pink Sheet -> (column index, slug,
# category, unit). Columns confirmed from the "Monthly Prices" sheet header.
ASSETS = [
    (8,  "ttf_gas_europe", "gas",      "USD/mmbtu"),   # ★ TTF, Europe
    (7,  "henryhub_gas_us", "gas",     "USD/mmbtu"),   # US reference
    (64, "copper",         "packaging", "USD/mt"),     # ★ DCB substrate, leadframes
    (62, "aluminum",       "packaging", "USD/mt"),     # bond wire, AlN
    (66, "tin",            "packaging", "USD/mt"),     # solder
    (71, "silver",         "packaging", "USD/troy_oz"),# sinter die-attach
    (69, "gold",           "packaging", "USD/troy_oz"),# bond wire
]


def _download():
    if not os.path.exists(LOCAL_XLSX):
        r = requests.get(PINK_URL, timeout=60)
        r.raise_for_status()
        with open(LOCAL_XLSX, "wb") as f:
            f.write(r.content)
    return LOCAL_XLSX


def _to_date(period):
    """'2022M01' -> '2022-01-01'."""
    y, m = str(period).split("M")
    return f"{int(y):04d}-{int(m):02d}-01"


def fetch_all():
    _download()
    wb = openpyxl.load_workbook(LOCAL_XLSX, read_only=True, data_only=True)
    ws = wb["Monthly Prices"]
    os.makedirs(OUT_DIR, exist_ok=True)

    series = {a[1]: [] for a in ASSETS}
    for row in ws.iter_rows(min_row=7, values_only=True):
        period = row[0]
        if not period or "M" not in str(period):
            continue
        if int(str(period).split("M")[0]) < START_YEAR:
            continue
        date = _to_date(period)
        for col, slug, _cat, _unit in ASSETS:
            v = row[col]
            if v in (None, "…", "..", "") or isinstance(v, str):
                continue
            series[slug].append((date, round(float(v), 4)))

    written = {}
    for col, slug, cat, unit in ASSETS:
        rows = series[slug]
        path = os.path.join(OUT_DIR, f"{slug}.csv")
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "price"])
            w.writerows(rows)
        written[slug] = {"path": path, "category": cat, "unit": unit, "n": len(rows),
                         "first": rows[0] if rows else None, "last": rows[-1] if rows else None}
    return written


if __name__ == "__main__":
    for slug, info in fetch_all().items():
        print(f"  {slug:16s} [{info['category']:9s}] {info['n']:3d} pts {info['unit']:11s} "
              f"{info['first'][0]}->{info['last'][0]}  last={info['last'][1]}")
