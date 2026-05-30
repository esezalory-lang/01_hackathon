"""
Layer 1 — Pair scoping (Featherless / Llama-4-Scout, no wrapper).

Given the company's procurement/treasury context AND a live economic calendar,
the small open model picks the currency pairs most worth a 6-month FX forecast.
Output pairs are resolved against config.PAIR_UNIVERSE (so each maps to a FRED
series). Any failure falls back to config.DEFAULT_PAIRS so the demo never breaks.
"""
import json

from openai import OpenAI

import config
from calendar_client import high_impact_by_currency

COMPANY_PROMPT = """You are the head of FX risk at Infineon Technologies, a European
power-semiconductor manufacturer. You report in EUR but pay for inputs in USD and
Asian currencies: Japanese (JPY) lithography/equipment, Chinese (CNY) gallium and
materials, Korean (KRW) and Taiwanese (TWD) substrates and packaging."""

SCOPING_PROMPT_TEMPLATE = """{company}

This week's high/medium-impact macro events by currency (from the economic calendar):
{calendar}

From this universe of tradable pairs only:
{universe}

Pick the 4-6 currency pairs you most need a 6-month probabilistic forecast for,
given the company's exposures and the macro events above.

For each pair return:
- pair: must be EXACTLY one of the universe strings (e.g. "EUR/USD")
- reason: why it matters to the company (1 sentence)
- watch_events: 1-3 calendar events most likely to move it
- decision: the hedging decision it informs (1 sentence)

Return ONLY a JSON object of the form {{"pairs": [ {{...}}, {{...}} ]}}.
No markdown, no preamble."""


def _build_prompt():
    cal = high_impact_by_currency()
    cal_lines = "\n".join(f"- {cur}: {', '.join(titles[:4])}" for cur, titles in cal.items()) or "- (none)"
    universe = ", ".join(config.PAIR_UNIVERSE.keys())
    return SCOPING_PROMPT_TEMPLATE.format(
        company=COMPANY_PROMPT, calendar=cal_lines, universe=universe)


def _coerce_to_list(content):
    parsed = json.loads(content)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        # Prefer an explicit "pairs" key, then any list of objects, then any list.
        if isinstance(parsed.get("pairs"), list):
            return parsed["pairs"]
        for v in parsed.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
        # A single pair object returned bare -> wrap it.
        if parsed.get("pair"):
            return [parsed]
        for v in parsed.values():
            if isinstance(v, list):
                return v
    raise ValueError("no JSON array found in model output")


def _resolve(items):
    """Keep only entries whose pair is in the universe; attach FRED metadata."""
    resolved = []
    seen = set()
    for it in items:
        if isinstance(it, str):
            it = {"pair": it}
        elif not isinstance(it, dict):
            continue
        pair = (it.get("pair") or it.get("symbol") or "").upper().strip()
        if pair in config.PAIR_UNIVERSE and pair not in seen:
            seen.add(pair)
            meta = config.PAIR_UNIVERSE[pair]
            resolved.append({
                "pair": pair,
                "slug": config.pair_slug(pair),
                "fred_id": meta["fred_id"],
                "quote": meta["quote"],
                "reason": it.get("reason", ""),
                "watch_events": it.get("watch_events", []),
                "decision": it.get("decision", ""),
            })
    return resolved


def _fallback():
    out = []
    for pair in config.DEFAULT_PAIRS:
        meta = config.PAIR_UNIVERSE[pair]
        out.append({
            "pair": pair,
            "slug": config.pair_slug(pair),
            "fred_id": meta["fred_id"],
            "quote": meta["quote"],
            "reason": "Core Infineon FX exposure (EUR reporting vs USD/Asian input costs).",
            "watch_events": [],
            "decision": "Set the 6-month forward hedge ratio for this exposure.",
        })
    return out


def scope_pairs():
    """Return the scoped list of pair dicts (resolved to the FRED universe)."""
    if not config.FEATHERLESS_API_KEY:
        return _fallback()
    try:
        client = OpenAI(base_url="https://api.featherless.ai/v1",
                        api_key=config.FEATHERLESS_API_KEY)
        response = client.chat.completions.create(
            model=config.FEATHERLESS_MODEL,
            messages=[
                {"role": "system", "content": "You output ONLY valid JSON arrays. No markdown, "
                                              "no preamble. Start with [ and end with ]."},
                {"role": "user", "content": _build_prompt()},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=2000,
        )
        resolved = _resolve(_coerce_to_list(response.choices[0].message.content))
        return resolved if resolved else _fallback()
    except Exception as e:  # noqa: BLE001 — demo stability over precision
        print(f"[step1_scope] LLM call failed, using fallback: {e}")
        return _fallback()


if __name__ == "__main__":
    print(json.dumps(scope_pairs(), indent=2))
