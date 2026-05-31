# Infineon Chip Cost Agent — Project Spec

## What this is
A procurement decision agent for a power-semiconductor manufacturer (Infineon).
It forecasts key cost inputs, classifies signals as weak/strong, and recommends
hedging/trading strategies with backtest validation.

Built for the Sybilion hackathon (36h). Demo is Sunday.

---

## Pipeline (4 steps)

```
[Step 1: Scope]        [Step 2: Forecast]       [Step 3: Decide]        [Step 4: Backtest]
LLM identifies    -->  Sybilion API returns  --> Strong signals only --> Walk-forward test
what to forecast       bands + drivers           get trade recs          of the strategy
= D1 (asset list)      = D2 (forecasts)          = D3 (strategy)         = confidence
```

### Step 1 — D1: Asset Scoping (Claude Sonnet via API)

Call the Anthropic API with this system prompt to get a structured asset list:

```
You are the head of procurement at Infineon Technologies, a European
power semiconductor manufacturer. Your fabs in Villach (Austria) and
Dresden (Germany) produce silicon, silicon carbide (SiC), and gallium
nitride (GaN) power chips.

Your cost stack: electricity (largest controllable input), substrate
materials (silicon, SiC, GaN/gallium), packaging metals (copper,
aluminum, tin, silver, gold), freight, and EUR/USD exposure.

Given current geopolitical risks (China gallium export controls,
EU energy volatility, shipping disruptions), list exactly one asset
per category that you most need a 6-month probabilistic forecast for.

Categories: power, fx, materials, shipping

For each, return:
- series: the specific index/commodity name
- category: power | fx | materials | shipping
- reason: why it matters to chip cost (1 sentence)
- decision: the hedging decision it informs (1 sentence)
- keywords: 5-8 search keywords for the Sybilion driver search

Return ONLY a JSON array. No markdown, no preamble.
```

**Expected output (hardcode this as fallback for demo stability):**
```json
[
  {
    "series": "Austria Day-Ahead Power Price",
    "category": "power",
    "reason": "SiC crystal growth at >2000C makes electricity the largest controllable fab cost",
    "decision": "Lock PPA strike or hedge via EEX power futures",
    "keywords": ["TTF gas", "EU ETS carbon", "wind generation", "Austrian grid load", "renewable share", "gas storage", "hydro reservoir"]
  },
  {
    "series": "EUR/USD",
    "category": "fx",
    "reason": "All commodity inputs price in USD but Infineon reports in EUR",
    "decision": "FX forward hedge ratio for next 6 months of USD-denominated purchases",
    "keywords": ["ECB rate", "Fed funds", "eurozone CPI", "US employment", "trade balance", "German PMI"]
  },
  {
    "series": "Gallium",
    "category": "materials",
    "reason": "Core input for GaN-on-Si wafers at the new Villach 300mm line",
    "decision": "Pre-buy gallium inventory or wait given China export controls",
    "keywords": ["China export controls", "gallium supply", "bauxite", "alumina", "GaN demand", "semiconductor capacity"]
  },
  {
    "series": "Shanghai Container Freight Index",
    "category": "shipping",
    "reason": "Materials and substrates ship Asia-Europe, finished dies ship globally",
    "decision": "Lock freight forward or spot-buy shipping",
    "keywords": ["Red Sea", "container rates", "port congestion", "bunker fuel", "China exports", "Suez Canal"]
  }
]
```

### Step 2 — D2: Sybilion Forecasts

For each asset in D1, call Sybilion:

```
POST /api/v1/forecasts
{
  "pipeline_version": "v1",
  "frequency": "monthly",
  "soft_horizon": 6,
  "backtest": true,
  "timeseries": { "2020-01-01": 45.2, "2020-02-01": 47.1, ... },
  "timeseries_metadata": {
    "title": "Austria Day-Ahead Power Price",
    "description": "Monthly average wholesale day-ahead electricity price for Austrian bidding zone (BZN|AT) in EUR/MWh",
    "keywords": ["TTF gas", "EU ETS carbon", "wind generation", ...]
  }
}
```

Then poll: `GET /api/v1/forecasts/:id` until status = "completed"

Then read: `GET /api/v1/forecasts/:id/artifacts/forecast.json`

**D2 output per asset (normalize to this shape):**
```json
{
  "asset": "Austria Day-Ahead Power",
  "category": "power",
  "current_price": 82.5,
  "forecast": [
    { "month": 1, "p10": 68, "p50": 85, "p90": 108 },
    { "month": 2, "p10": 65, "p50": 87, "p90": 115 },
    ...
  ],
  "drivers": [
    { "name": "TTF gas", "importance": 0.34, "direction": "up" },
    { "name": "Wind generation", "importance": 0.22, "direction": "down" },
    ...
  ],
  "backtest": { "mape": 6.4, "baseline_mape": 18.2 }
}
```

### Step 2.5 — Signal Classification (WEAK / STRONG)

This is the mechanical logic — NOT an LLM call:

```python
def classify_signal(forecast):
    p10_6 = forecast["forecast"][-1]["p10"]
    p50_6 = forecast["forecast"][-1]["p50"]
    p90_6 = forecast["forecast"][-1]["p90"]
    current = forecast["current_price"]

    band_width = (p90_6 - p10_6) / p50_6        # relative uncertainty
    price_move = abs(p50_6 - current) / current  # expected magnitude
    mape = forecast["backtest"]["mape"]

    # Strong signal = high conviction move (narrow bands + big move + good backtest)
    # OR high risk (very wide bands = must hedge)
    is_strong = (
        (band_width > 0.4) or                    # wide bands = high risk, must act
        (price_move > 0.08 and mape < 15) or     # >8% move with decent accuracy
        (band_width > 0.25 and price_move > 0.05) # moderate both
    )

    return {
        **forecast,
        "signal": "STRONG" if is_strong else "WEAK",
        "band_width": round(band_width, 3),
        "price_move": round(price_move, 3),
        "direction": "UP" if p50_6 > current else "DOWN"
    }
```

### Step 3 — D3: Strategy (LLM on strong signals only)

Filter to STRONG signals only. Feed them to Claude Sonnet with this prompt:

```
You are a quantitative strategist at Infineon's treasury desk.

Based on these Sybilion forecast outputs (strong signals only), recommend
ONE specific trade per strong signal. For each trade, specify:
- asset: what you're trading
- action: BUY/SELL/HEDGE and the instrument (futures, forward, PPA, spot)
- size: percentage of exposure to hedge (10-90%)
- rationale: 2 sentences using the band width, direction, and top driver
- entry_trigger: what price level or event triggers execution
- stop_condition: when to exit or revisit

The demo trade should be the FX one (EUR/USD or USD/JPY) since it's
easiest to backtest with public data.

Return ONLY a JSON array. No markdown.

Strong signals:
{strong_signals_json}
```

### Step 4 — Backtest

For the demo FX trade, run a simple walk-forward:

```python
def backtest_strategy(historical_prices, strategy, lookback_months=18):
    """
    Walk forward: at each month, pretend you ran the signal classifier.
    If STRONG + direction matches strategy.action, execute the trade.
    Track P&L vs buy-and-hold.
    """
    results = []
    for i in range(lookback_months, len(historical_prices)):
        window = historical_prices[i-lookback_months:i]
        current = window[-1]
        # Simple momentum proxy for backtest (real version uses Sybilion)
        sma = sum(window) / len(window)
        signal_up = current > sma
        
        if strategy["action"] == "SELL" and not signal_up:
            pnl = current - historical_prices[i]  # short profit
        elif strategy["action"] == "BUY" and signal_up:
            pnl = historical_prices[i] - current   # long profit
        else:
            pnl = 0  # no trade
        
        results.append({
            "month": i,
            "price": historical_prices[i],
            "traded": pnl != 0,
            "pnl": pnl,
            "cumulative_pnl": sum(r["pnl"] for r in results) + pnl
        })
    
    return {
        "trades": results,
        "total_pnl": sum(r["pnl"] for r in results),
        "win_rate": sum(1 for r in results if r["pnl"] > 0) / max(sum(1 for r in results if r["traded"]), 1),
        "max_drawdown": min(r["cumulative_pnl"] for r in results)
    }
```

---

## UI Layout (matches whiteboard)

```
┌─────────────────────────────────────────────────────────┐
│  Infineon · Chip Cost Procurement Agent                 │
├─────────────────────────┬───────────────────────────────┤
│                         │  D2 Signal Classification     │
│   MAIN FORECAST CHART   │  ┌─────────┐ ┌─────────────┐ │
│   (largest, #1)         │  │  WEAK   │ │   STRONG    │ │
│   - history line        │  │ Power   │ │ FX: EUR/USD │ │
│   - P10/P50/P90 fan     │  │ Ship.   │ │ Gallium     │ │
│   - backtest MAPE badge │  └─────────┘ └──────┬──────┘ │
│                         │                     │        │
├────────┬────────┬───────┤                     ▼        │
│ THUMB  │ THUMB  │ MAPE  │  Agent / Strategy Panel      │
│  #2    │  #3    │ badge │  ┌───────────────────────┐   │
│(other  │(other  │       │  │ EUR/USD: SELL forward │   │
│assets) │assets) │       │  │ Gallium: PRE-BUY spot │   │
│        │        │       │  │ Confidence: 78%       │   │
├────────┴────────┴───────┤  └───────────────────────┘   │
│                         │                               │
│   BACKTEST P&L CURVE    │  Driver importance bars       │
│   cumulative returns    │  (top 5 drivers for selected) │
│   vs buy-and-hold       │                               │
│                         │                               │
├─────────────────────────┴───────────────────────────────┤
│  [Gas shock ↗]  [Gallium ban ↗]  [Cold snap ↗]  shock  │
└─────────────────────────────────────────────────────────┘
```

### Clicking behavior:
- Click a STRONG signal card → main chart updates to that asset's forecast
- Click a WEAK signal card → main chart updates but strategy panel grays out
- Click a shock button → re-runs Step 2 with modified assumptions → all panels update
- Thumbnails #2 and #3 show the other two forecasted assets (not currently selected)

---

## Tech Stack

- **Frontend:** React + Tailwind (via Lovable or manual)
- **Backend/API layer:** Python (FastAPI or plain scripts)
- **LLM calls:** Anthropic API (Claude Sonnet) for Steps 1 and 3
- **Forecasting:** Sybilion API for Step 2
- **Data:** Pre-fetched CSVs for the demo assets (see data sources below)

## Data Sources (pre-fetch these CSVs)

| Asset | Source | Format |
|-------|--------|--------|
| AT power price | Ember wholesale data or APG ZIP | Monthly EUR/MWh |
| EUR/USD | FRED `DEXUSEU` | Daily → resample monthly |
| Gallium | TradingEconomics or SMM | Monthly USD/kg |
| SCFI (shipping) | Shanghai Shipping Exchange | Monthly index |
| Copper (backup) | FRED `PCOPPUSDM` | Monthly USD/mt |

## Environment Variables

```
ANTHROPIC_API_KEY=sk-ant-...
SYBILION_API_KEY=...
SYBILION_BASE_URL=https://api.sybilion.dev
```

## File Structure

```
/
├── AGENT_SPEC.md          # this file
├── .env                   # API keys
├── config.py              # reads .env, defines asset configs
├── data/
│   ├── at_power.csv       # monthly AT wholesale power
│   ├── eurusd.csv         # monthly EUR/USD
│   ├── gallium.csv        # monthly gallium price
│   └── scfi.csv           # monthly SCFI index
├── pipeline/
│   ├── step1_scope.py     # LLM call → D1 asset list (with hardcoded fallback)
│   ├── step2_forecast.py  # Sybilion calls → D2 forecasts + signal classification
│   ├── step3_strategy.py  # LLM call on strong signals → D3 trades
│   └── step4_backtest.py  # walk-forward backtest on recommended trades
├── sybilion_client.py     # thin wrapper around 3 Sybilion API calls
├── mock_sybilion.py       # mock responses for UI dev before API is wired
├── app.py                 # FastAPI server exposing /run-pipeline, /forecast/:asset, /backtest
└── frontend/              # React app (or Lovable project)
    └── ...
```

## Mock Data (for UI development before API is wired)

Use `mock_sybilion.py` to return realistic responses so the frontend
can be built in parallel. The mock should return the same shape as
the normalized D2 output above. Switch to real API by changing one import.

## Demo Script (Sunday)

1. Show the dashboard with 4 assets pre-forecasted
2. Walk through: "The agent scoped 4 cost inputs for Infineon..."
3. Show signal classification: "Power and shipping are WEAK — bands tight, no action needed"
4. Show strong signals: "EUR/USD and gallium are STRONG — here's why..."
5. Show the FX trade recommendation with rationale
6. Show the backtest: "If you'd followed this signal for the last 18 months..."
7. **SHOCK:** Click "Gallium export ban" → everything re-runs → gallium moves from WEAK to STRONG → new trade appears
8. "The agent adapted. The recommendation changed. That's what probabilistic forecasting enables."
