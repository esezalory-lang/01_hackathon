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


# ---------------------------------------------------------------------------
# Operations-driven scoping: pick pairs from WHERE Infineon manufactures/pays,
# not from this week's calendar. Used by the Qwen-scoped monthly signal loop.
# ---------------------------------------------------------------------------
OPERATIONS_CONTEXT = """Infineon's operational footprint — where it manufactures,
runs major back-end (assembly/test) or sales sites, and the currency it pays in:
- Austria — Villach & Graz front-end fabs (EUR)
- Germany — Dresden & Regensburg fabs + Munich HQ (EUR)
- USA — design, sales, some manufacturing (USD)
- Singapore & Malaysia — back-end assembly/test hubs (SGD is the tradable proxy)
- China — Wuxi back-end + materials sourcing incl. gallium (CNY)
- South Korea — substrate & memory supply (KRW)
- Taiwan — foundry (TSMC) and advanced packaging (TWD)
- Japan — lithography/equipment imports (JPY)
- India — growing design & operations (INR)
Infineon reports in EUR, so EUR strength/weakness vs the USD and these Asian
currencies is what drives its hedging needs."""

OPERATIONS_PROMPT_TEMPLATE = """{company}

{operations}

From this universe of tradable pairs only:
{universe}

Pick EXACTLY 6 currency pairs Infineon most needs a monthly probabilistic
forecast for, chosen specifically from WHERE it operates and pays costs (the
footprint above) — not from short-term news. Make sure your 6 span its main
exposures: Europe (EUR), the US (USD) and the Asian manufacturing currencies
(CNY, KRW, TWD, and SGD/INR where relevant).

For each pair return:
- pair: must be EXACTLY one of the universe strings (e.g. "EUR/USD")
- site: the Infineon location/operation that creates this exposure (few words)
- reason: why this FX pair matters to that operation (1 sentence)
- decision: the hedging decision it informs (1 sentence)

Return ONLY a JSON object of the form {{"pairs": [ {{...}}, {{...}} ]}}.
No markdown, no preamble."""


def _build_operations_prompt():
    universe = ", ".join(config.PAIR_UNIVERSE.keys())
    return OPERATIONS_PROMPT_TEMPLATE.format(
        company=COMPANY_PROMPT, operations=OPERATIONS_CONTEXT, universe=universe)


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
                "site": it.get("site", ""),
                "reason": it.get("reason", ""),
                "watch_events": it.get("watch_events", []),
                "decision": it.get("decision", ""),
            })
    return resolved


_OPS_SITE = {
    "EUR/USD": "Villach/Dresden fabs vs USD costs",
    "USD/JPY": "Japan lithography/equipment imports",
    "USD/CNY": "Wuxi back-end + China materials",
    "USD/KRW": "Korean substrate/memory supply",
    "USD/TWD": "Taiwan foundry & packaging",
    "USD/SGD": "Singapore/Malaysia back-end hubs",
    "USD/INR": "India design & operations",
}

# Operations-priority order used to backfill if the model under-selects.
_OPS_PRIORITY = ["EUR/USD", "USD/JPY", "USD/CNY", "USD/KRW", "USD/TWD", "USD/SGD", "USD/INR"]


def _ops_entry(pair):
    meta = config.PAIR_UNIVERSE[pair]
    return {
        "pair": pair, "slug": config.pair_slug(pair),
        "fred_id": meta["fred_id"], "quote": meta["quote"],
        "site": _OPS_SITE.get(pair, ""),
        "reason": "Core Infineon FX exposure from its operational footprint.",
        "watch_events": [], "decision": "Set the monthly forward hedge ratio for this exposure.",
    }


def _backfill_ops(resolved, target=6):
    """Keep the model's picks first, then top up from the ops-priority set."""
    seen = {r["pair"] for r in resolved}
    for pair in _OPS_PRIORITY:
        if len(resolved) >= target:
            break
        if pair not in seen:
            resolved.append(_ops_entry(pair))
            seen.add(pair)
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
            "site": _OPS_SITE.get(pair, ""),
            "reason": "Core Infineon FX exposure (EUR reporting vs USD/Asian input costs).",
            "watch_events": [],
            "decision": "Set the 6-month forward hedge ratio for this exposure.",
        })
    return out


def scope_pairs_by_operations():
    """Qwen picks the pairs Infineon needs to hedge GIVEN where it operates/pays.

    Same FRED-resolved shape as scope_pairs(), but driven by the manufacturing
    footprint rather than the week's calendar. Falls back to DEFAULT_PAIRS.
    """
    if not config.FEATHERLESS_API_KEY:
        return _fallback()
    try:
        client = OpenAI(base_url="https://api.featherless.ai/v1",
                        api_key=config.FEATHERLESS_API_KEY)
        response = client.chat.completions.create(
            model=config.FEATHERLESS_MODEL,
            messages=[
                {"role": "system", "content": "You output ONLY valid JSON. No markdown, no preamble."},
                {"role": "user", "content": _build_operations_prompt()},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=2000,
        )
        resolved = _resolve(_coerce_to_list(response.choices[0].message.content))
        # Backfill a site label if the model omitted it.
        for r in resolved:
            r["site"] = r.get("site") or _OPS_SITE.get(r["pair"], "")
        if not resolved:
            return _fallback()
        # The model occasionally under-selects; top up to a full ops board.
        return _backfill_ops(resolved, target=6)
    except Exception as e:  # noqa: BLE001 — demo stability over precision
        print(f"[step1_scope] operations scoping failed, using fallback: {e}")
        return _fallback()


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
