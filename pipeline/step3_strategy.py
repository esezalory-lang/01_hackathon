"""
Layer 3 — Strategy (Claude Sonnet on the strongest pairs only).

Takes the high-confidence pairs from Layer 2 and recommends ONE concrete FX trade
each. If Anthropic is unavailable, a deterministic fallback derives the trade from
the forecast so the demo always shows recommendations.
"""
import json

import config

STRATEGY_PROMPT = """You are a quantitative FX strategist at Infineon's treasury desk.

Based on these Sybilion forecasts (highest-confidence currency pairs only),
recommend ONE specific trade per pair. For each, specify:
- pair: the currency pair
- action: BUY/SELL/HEDGE and the instrument (FX forward, option, spot)
- size: percentage of exposure to hedge (10-90)
- rationale: 2 sentences using the confidence, band width, direction and top driver
- entry_trigger: the price level or macro event that triggers execution
- stop_condition: when to exit or revisit

Return ONLY a JSON array. No markdown.

Strong pairs:
{strong_pairs_json}"""


def _top_driver(p):
    drivers = p.get("drivers") or []
    return drivers[0]["name"] if drivers else "the lead macro driver"


def _fallback_trade(p):
    direction = p["direction"]
    move_pct = round(p["price_move"] * 100, 1)
    size = int(min(90, max(10, round(p["confidence"] * 0.9))))
    action = f"SELL {p['pair']} forward" if direction == "DOWN" else f"BUY {p['pair']} forward"
    return {
        "pair": p["pair"],
        "action": action,
        "size": size,
        "rationale": (
            f"{p['pair']} forecasts a {direction} move of ~{move_pct}% over 3 months at "
            f"{p['confidence']:.0f}% confidence (band width {p['band_width']:.0%}); "
            f"{_top_driver(p)} is the dominant driver. Hedging {size}% of exposure locks the "
            f"rate while leaving upside."
        ),
        "entry_trigger": f"Execute as spot approaches the 3-month p50 ({p['forecast'][-1]['p50']}).",
        "stop_condition": "Revisit if price exits the p10-p90 band or the lead driver reverses.",
    }


def _parse(content):
    parsed = json.loads(content)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for v in parsed.values():
            if isinstance(v, list):
                return v
    raise ValueError("no JSON array of trades found")


def recommend_strategy(strong_pairs):
    """Trade recs for the strongest pairs (D3)."""
    if not strong_pairs:
        return []
    fallback = [_fallback_trade(p) for p in strong_pairs]

    if not config.ANTHROPIC_API_KEY:
        return fallback
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        slim = [{
            "pair": p["pair"], "current_price": p["current_price"], "direction": p["direction"],
            "confidence": p["confidence"], "band_width": p["band_width"],
            "price_move": p["price_move"], "forecast_3m": p["forecast"][-1],
            "top_drivers": (p.get("drivers") or [])[:3], "backtest": p.get("backtest", {}),
        } for p in strong_pairs]
        msg = client.messages.create(
            model=config.ANTHROPIC_MODEL, max_tokens=1500,
            messages=[{"role": "user",
                       "content": STRATEGY_PROMPT.format(strong_pairs_json=json.dumps(slim, indent=2))}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text")
        trades = _parse(text)
        return trades if trades else fallback
    except Exception as e:  # noqa: BLE001
        print(f"[step3_strategy] LLM call failed, using fallback: {e}")
        return fallback


if __name__ == "__main__":
    from pipeline.step2_forecast import run, select_strongest
    res = run(use_mock=True)
    print(json.dumps(recommend_strategy(select_strongest(res)), indent=2))
