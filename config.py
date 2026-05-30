"""
config.py — the ONE place you configure this project. Two things live here:

  1. CREDENTIALS — they do NOT go in this file. They live in .env (gitignored).
     This file only READS them. See .env.example for the template.

  2. DOMAIN — the single decision you and your partner make. Fill ACTIVE_DOMAIN
     once you've chosen a subject. Until then it stays generic. The subject is
     deliberately open — examples are listed at the bottom for inspiration only.
"""
import os
from dotenv import load_dotenv

load_dotenv()  # pulls .env into the environment

# ---------------------------------------------------------------------------
# CREDENTIALS  (read from .env — never hardcode a key in this file)
# ---------------------------------------------------------------------------
SYBILION_API_KEY    = os.environ.get("SYBILION_API_KEY")
SYBILION_BASE_URL   = os.environ.get("SYBILION_BASE_URL", "https://api.sybilion.dev")
FEATHERLESS_API_KEY = os.environ.get("FEATHERLESS_API_KEY")

# ---------------------------------------------------------------------------
# DOMAIN  (the one thing to decide — fill in when you pick your subject)
# ---------------------------------------------------------------------------
ACTIVE_DOMAIN = {
    "title":       "TODO: a 20-511 char descriptive title for your monthly series",
    "description": "TODO: what the series is, its units, and the decision it informs (<=2048 chars)",
    "keywords":    [],  # TODO: 4-20 contextual keywords (these steer the driver search)
    "soft_horizon": 6,  # 6 = sweet spot (needs >=60 monthly points)
    # Rename these to fit your decision once chosen:
    "actions":     {"act": "ACT_NOW", "wait": "WAIT", "hedge": "HEDGE"},
}

# Inspiration only — pick anything, including something NOT on this list

