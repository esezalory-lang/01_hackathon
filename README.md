# Forecasting Decision Agent — Starter

A decision agent on the Sybilion forecasting API. The engine decides, the LLM only
narrates, and the agent adapts when an assumption changes. Subject is OPEN — you pick.

## You only edit two places

| What | Where | When |
|---|---|---|
| **Your API keys** | `.env` (copy from `.env.example`) | now |
| **Your domain/subject** | `config.py` → `ACTIVE_DOMAIN` | when you & your partner decide |

Everything else runs unchanged.

## 1. Put your credentials in `.env`  (the ONLY place keys go)

```bash
cp .env.example .env
```
Open `.env` and replace the placeholders:
```
SYBILION_API_KEY=<your sybilion key>
FEATHERLESS_API_KEY=<your featherless key>
```
That's it. `config.py` reads them automatically; no other file needs your keys.
`.env` is gitignored — never commit it, never paste keys in chat.

## 2. Install + run on the mock (no domain needed yet)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python3 adaptation.py    # watch a decision flip under a shock
python3 backtest.py      # policy vs naive baseline
python3 explain.py       # plain-language narration (uses Featherless if key set)
streamlit run app.py     # the dashboard
```

## 3. When you pick a subject, fill `config.py` → `ACTIVE_DOMAIN`

Set the title, description, keywords, and rename the actions to fit your decision.
Then swap the data source: replace `mock_sybilion` with `sybilion_client` in
`app.py` / `backtest.py`, drop your real monthly series into `data/series.csv`,
and finish `_normalize()` in `sybilion_client.py` using one real forecast artifact.

## Files
```
config.py            <- KEYS read here (from .env) + ACTIVE_DOMAIN to fill
.env.example         <- copy to .env, paste keys
sybilion_client.py   real API client (confirmed schema)
mock_sybilion.py     offline mock, same shape — build before data is ready
decision_engine.py   the core logic — pure function, explicit thresholds
adaptation.py        shock -> re-run -> diff (the live-demo capability)
backtest.py          replay policy over history vs naive baseline
explain.py           LLM narration via Featherless (key read from config)
app.py               Streamlit dashboard (visible reasoning + shock buttons)
data/                your series.csv + sourcing notes
```
