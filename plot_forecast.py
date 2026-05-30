"""Render the Sybilion Austria power-price forecast: history + median + IC bands."""

import json
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter

HIST = "#378ADD"
FC = "#D85A30"

# History (the series we submitted)
hist = pd.read_csv("data/at_power_monthly.csv", parse_dates=["date"]).set_index("date")["price"]

# Forecast series (pasted from forecast.json)
fc = {
    "2026-06-01": {"m": 108.27721, "q10": 69.225, "q90": 147.32942, "q05": 50.2729, "q95": 166.281521},
    "2026-07-01": {"m": 111.097053, "q10": 73.850862, "q90": 148.343243, "q05": 62.108108, "q95": 160.085997},
    "2026-08-01": {"m": 112.904707, "q10": 80.466894, "q90": 145.34252, "q05": 49.367711, "q95": 176.441703},
    "2026-09-01": {"m": 114.252365, "q10": 79.325155, "q90": 149.179574, "q05": 25.84527, "q95": 202.659459},
    "2026-10-01": {"m": 115.640429, "q10": 60.194128, "q90": 171.086729, "q05": 13.151187, "q95": 218.129671},
    "2026-11-01": {"m": 116.861439, "q10": 56.335735, "q90": 177.387143, "q05": -7.995371, "q95": 241.71825},
}
f = pd.DataFrame(fc).T
f.index = pd.to_datetime(f.index)

# Junction: prepend last historical point so lines/bands are continuous
last_d, last_v = hist.index[-1], hist.iloc[-1]
for col in f.columns:
    f.loc[last_d, col] = last_v
f = f.sort_index()

fig, ax = plt.subplots(figsize=(13, 6))

# show last ~3 years of history for readability
ax.plot(hist.index, hist.values, color=HIST, lw=1.4, label="History (actual)")

ax.fill_between(f.index, f["q05"], f["q95"], color=FC, alpha=0.12, label="IC 90% (0.05–0.95)")
ax.fill_between(f.index, f["q10"], f["q90"], color=FC, alpha=0.25, label="IC 80% (0.10–0.90)")
ax.plot(f.index, f["m"], color=FC, lw=2.0, marker="o", ms=4, label="Forecast (median)")

ax.set_ylim(-47.70, 527.97)  # from context.json
ax.set_xlim(hist.index.min(), pd.Timestamp("2027-02-01"))
ax.set_title("Austria Day-Ahead Wholesale Electricity Price — Monthly Avg (EUR/MWh)\nSybilion v1 forecast, Jun–Nov 2026", fontsize=12)
ax.set_ylabel("EUR / MWh")
ax.xaxis.set_major_formatter(DateFormatter("%Y"))
ax.grid(True, alpha=0.25)
ax.legend(loc="upper left", fontsize=9)
fig.tight_layout()
fig.savefig("data/at_forecast.png", dpi=130)
print("saved data/at_forecast.png")

# Also write a tidy forecast CSV
out = pd.DataFrame({
    "date": f.index[f.index > last_d].strftime("%Y-%m-%d"),
    "forecast_eur_mwh": f.loc[f.index > last_d, "m"].round(2).values,
    "ic80_low": f.loc[f.index > last_d, "q10"].round(2).values,
    "ic80_high": f.loc[f.index > last_d, "q90"].round(2).values,
    "ic90_low": f.loc[f.index > last_d, "q05"].round(2).values,
    "ic90_high": f.loc[f.index > last_d, "q95"].round(2).values,
})
out.to_csv("data/at_forecast.csv", index=False)
print(out.to_string(index=False))
