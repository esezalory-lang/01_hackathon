"""Filter the European daily wholesale price dataset down to Austria and
resample to a monthly average series for the first Sybilion forecast run.

Input : data/european_wholesale_electricity_price_data_daily.csv
        columns -> Country, ISO3 Code, Date, Price (EUR/MWhe)
Output: data/at_power_monthly.csv
        columns -> date, price   (monthly avg EUR/MWh, one row per month)
"""

import pandas as pd

SRC = "data/european_wholesale_electricity_price_data_daily.csv"
DST = "data/at_power_monthly.csv"

df = pd.read_csv(SRC, parse_dates=["Date"])

# Keep Austria only (ISO3 == AUT is the unambiguous filter).
at = df[df["ISO3 Code"] == "AUT"].copy()

# Daily -> monthly mean, indexed at month start (MS).
monthly = (
    at.set_index("Date")["Price (EUR/MWhe)"]
    .resample("MS")
    .mean()
    .round(2)
    .rename("price")
)

# Drop the trailing partial month if it has fewer days than expected coverage.
monthly.index.name = "date"
monthly.to_csv(DST)

print(f"rows: {len(monthly)}")
print(f"range: {monthly.index.min().date()} -> {monthly.index.max().date()}")
print(monthly.head())
print(monthly.tail())
