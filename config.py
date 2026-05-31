"""
config.py — the ONE place you configure this project (FX treasury agent).

Flow:
  Layer 1  Featherless (Llama-4-Scout) reads the company prompt + a live
           economic calendar  -> currency PAIRS to watch.
  Layer 2  FRED gives monthly history (2023->now); an hourly feed refreshes
           the current month -> Sybilion forecast (filters.limit=0, 3m horizon).
  Layer 3  Rank pairs by forecast CONFIDENCE -> return the strongest only.

Credentials live in .env (gitignored); this file only READS them.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# CREDENTIALS
# ---------------------------------------------------------------------------
SYBILION_API_KEY    = os.environ.get("SYBILION_API_KEY")
SYBILION_BASE_URL   = os.environ.get("SYBILION_BASE_URL", "https://api.sybilion.dev")
FEATHERLESS_API_KEY = os.environ.get("FEATHERLESS_API_KEY")
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY")
# Optional: hourly intraday FX provider (Twelve Data free tier supports 1h FX).
TWELVEDATA_API_KEY  = os.environ.get("TWELVEDATA_API_KEY")
FRED_API_KEY        = os.environ.get("FRED_API_KEY")  # optional; keyless CSV used if absent

# ---------------------------------------------------------------------------
# FLAGS
# ---------------------------------------------------------------------------
# USE_MOCK=True -> serve mock_sybilion data (no live calls). USE_MOCK=0 to go live.
USE_MOCK = os.environ.get("USE_MOCK", "1").lower() not in ("0", "false", "no")

# NOTE: Featherless does NOT host Llama-4-Scout (no Llama-4), and the Meta Llama-3.x
# models are gated (need HF access approval). Qwen2.5-7B-Instruct is a small, open,
# non-gated instruct model that works out of the box. Override via FEATHERLESS_MODEL.
FEATHERLESS_MODEL = os.environ.get("FEATHERLESS_MODEL", "Qwen/Qwen2.5-7B-Instruct")
ANTHROPIC_MODEL   = "claude-sonnet-4-6"                          # strategy (optional)

# ---------------------------------------------------------------------------
# DATA / FORECAST SETTINGS
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

FRED_START   = "2023-01-01"  # "max 2023" — monthly history start
SOFT_HORIZON = 3             # 41 monthly points >= 40 -> horizon 1-3 only
SYBILION_DRIVER_LIMIT = 0    # filters.limit = 0 -> no external driver datasets

# Pick the strongest pairs: confidence >= threshold (0-100). If none qualify,
# the pipeline returns the single highest-confidence pair so the UI never empties.
CONFIDENCE_THRESHOLD = 50.0

# ---------------------------------------------------------------------------
# PAIR UNIVERSE — currency pairs the agent may choose from, with the FRED
# series that quotes each pair in the orientation of its label.
#   DEXUSEU = USD per 1 EUR  -> "EUR/USD"
#   DEXJPUS = JPY per 1 USD  -> "USD/JPY"   (etc.)
# ---------------------------------------------------------------------------
PAIR_UNIVERSE = {
    "EUR/USD": {"fred_id": "DEXUSEU", "td_symbol": "EUR/USD", "quote": "USD per EUR"},
    "USD/JPY": {"fred_id": "DEXJPUS", "td_symbol": "USD/JPY", "quote": "JPY per USD"},
    "USD/CNY": {"fred_id": "DEXCHUS", "td_symbol": "USD/CNY", "quote": "CNY per USD"},
    "USD/KRW": {"fred_id": "DEXKOUS", "td_symbol": "USD/KRW", "quote": "KRW per USD"},
    "USD/TWD": {"fred_id": "DEXTAUS", "td_symbol": "USD/TWD", "quote": "TWD per USD"},
    "GBP/USD": {"fred_id": "DEXUSUK", "td_symbol": "GBP/USD", "quote": "USD per GBP"},
    "USD/CHF": {"fred_id": "DEXSZUS", "td_symbol": "USD/CHF", "quote": "CHF per USD"},
    "USD/CAD": {"fred_id": "DEXCAUS", "td_symbol": "USD/CAD", "quote": "CAD per USD"},
    "USD/MXN": {"fred_id": "DEXMXUS", "td_symbol": "USD/MXN", "quote": "MXN per USD"},
    "USD/SGD": {"fred_id": "DEXSIUS", "td_symbol": "USD/SGD", "quote": "SGD per USD"},
    "USD/INR": {"fred_id": "DEXINUS", "td_symbol": "USD/INR", "quote": "INR per USD"},
}

# Default pairs for a European power-semiconductor maker (Infineon): EUR base
# exposure + USD-denominated inputs from Asian suppliers (JP equipment, CN
# gallium, KR/TW substrates). Used as the Layer-1 fallback.
DEFAULT_PAIRS = ["EUR/USD", "USD/JPY", "USD/CNY", "USD/KRW", "USD/TWD"]


def pair_slug(pair):
    """'EUR/USD' -> 'eur_usd' (URL-safe id for /forecast/{pair})."""
    return pair.replace("/", "_").lower()


SLUG_TO_PAIR = {pair_slug(p): p for p in PAIR_UNIVERSE}

# ---------------------------------------------------------------------------
# 28 MAJOR PAIRS (initial FX backtest layer)
# 8 majors -> C(8,2) = 28 pairs, all derivable from 7 FRED USD-leg series.
# PRECEDENCE = conventional FX quoting hierarchy (higher = base currency).
# MAJOR_USD_LEGS maps each non-USD major to (fred_id, invert) so we can express
# every currency as USD-per-unit:  USD per X.  invert=True means the FRED series
# is X-per-USD (e.g. DEXJPUS = JPY per USD) so USD-per-X = 1/value.
# ---------------------------------------------------------------------------
MAJORS_PRECEDENCE = ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY"]
MAJOR_USD_LEGS = {
    "EUR": ("DEXUSEU", False),  # USD per EUR
    "GBP": ("DEXUSUK", False),  # USD per GBP
    "AUD": ("DEXUSAL", False),  # USD per AUD
    "NZD": ("DEXUSNZ", False),  # USD per NZD
    "JPY": ("DEXJPUS", True),   # JPY per USD -> invert
    "CHF": ("DEXSZUS", True),   # CHF per USD -> invert
    "CAD": ("DEXCAUS", True),   # CAD per USD -> invert
    # USD is the numeraire (USD per USD = 1.0)
}

# Forecast horizon for the initial layer: predict the UPCOMING month only.
SOFT_HORIZON_BACKTEST = 1

# Walk-forward monthly backtest: start history early enough that truncating to
# the month BEFORE each 2026 target still leaves >=40 monthly points for Sybilion
# (Jan 2026 target -> history ends Dec 2025; from 2022-01 that is 48 points).
BACKTEST_FRED_START = "2022-01-01"
BACKTEST_MONTHS = ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01"]
