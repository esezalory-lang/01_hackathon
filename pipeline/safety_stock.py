"""
Safety-stock sizing — a concrete decision rule on the forecast bands.

The forecasting ENGINE decides the buffer (deterministic, below); Qwen only
writes the one-line action message. Thesis: a wider probabilistic band = more
uncertainty = more buffer inventory of a critical material. An upward price bias
means pre-buy now (front-load) before it gets dearer; a downward bias means run
lean and delay the buy.

This stays a procurement/inventory decision — NOT process-sequence routing.
"""
import config

# Critical materials Infineon buffers (illustrative ops parameters).
MATERIALS = {
    "Gallium": {"price_unit": "USD/kg", "qty_unit": "kg", "weekly_use": 120,
                "base_buffer_weeks": 4, "lead_time_weeks": 8},
    "Copper":  {"price_unit": "USD/mt", "qty_unit": "mt", "weekly_use": 30,
                "base_buffer_weeks": 3, "lead_time_weeks": 4},
}

UNCERTAINTY_WEEKS_PER_BAND = 12.0  # band_width (relative half-width) -> extra weeks


def is_material(asset: str) -> bool:
    return asset in MATERIALS


def decide(asset: str, current_price: float, band_width: float,
           direction: str, confidence: float | None = None) -> dict:
    """Deterministic safety-stock decision from the forecast band. Pure function."""
    p = MATERIALS[asset]
    base = p["base_buffer_weeks"]

    # Wider band -> more buffer weeks (the core rule).
    uncertainty_weeks = round(band_width * UNCERTAINTY_WEEKS_PER_BAND)

    if direction == "UP":
        # Price rising: pre-buy to cover ~half the lead time before it gets dearer.
        directional_weeks = p["lead_time_weeks"] // 2
        action = "PRE-BUY & BUILD BUFFER"
        prebuy = True
    else:
        # Price falling: run lean, let buffer draw down, buy later cheaper.
        directional_weeks = -min(2, base // 2)
        action = "RUN LEAN / DELAY BUY"
        prebuy = False

    buffer_weeks = max(1, base + uncertainty_weeks + directional_weeks)
    delta_weeks = buffer_weeks - base
    buffer_qty = round(buffer_weeks * p["weekly_use"])
    buffer_value = round(buffer_qty * current_price)
    prebuy_qty = round(max(0, delta_weeks) * p["weekly_use"]) if prebuy else 0
    prebuy_value = round(prebuy_qty * current_price)

    return {
        "asset": asset,
        "action": action,
        "prebuy": prebuy,
        "base_buffer_weeks": base,
        "buffer_weeks": buffer_weeks,
        "delta_weeks": delta_weeks,
        "buffer_qty": buffer_qty,
        "qty_unit": p["qty_unit"],
        "buffer_value_usd": buffer_value,
        "prebuy_qty": prebuy_qty,
        "prebuy_value_usd": prebuy_value,
        "lead_time_weeks": p["lead_time_weeks"],
        "band_width": band_width,
        "direction": direction,
        "current_price": current_price,
        "price_unit": p["price_unit"],
        "confidence": confidence,
        "trigger": (f"Spot near {current_price} {p['price_unit']}"
                    if prebuy else f"Hold; revisit if band narrows or spot drops"),
    }


def _fallback_message(d: dict) -> str:
    if d["prebuy"]:
        return (f"{d['asset']} band ±{d['band_width']*100:.0f}% with upward bias — lift buffer to "
                f"{d['buffer_weeks']} weeks (+{d['delta_weeks']}) and pre-buy {d['prebuy_qty']} "
                f"{d['qty_unit']} (~${d['prebuy_value_usd']:,}) now before it gets dearer.")
    return (f"{d['asset']} band ±{d['band_width']*100:.0f}% with downward bias — run lean at "
            f"{d['buffer_weeks']} weeks and delay the buy; let the buffer draw down.")


def narrate(decision: dict) -> str:
    """Qwen writes ONE buyer-ready action sentence. Engine numbers are fixed."""
    key = config.FEATHERLESS_API_KEY
    if not key:
        return _fallback_message(decision)
    try:
        from openai import OpenAI
        client = OpenAI(base_url="https://api.featherless.ai/v1", api_key=key)
        prompt = (
            "You are Infineon's materials procurement desk. A forecasting engine has ALREADY made "
            "this safety-stock decision — do NOT change any number. Write ONE concrete action "
            "sentence (<=30 words) a buyer acts on today: state the buffer weeks, the pre-buy or "
            "draw-down action and quantity, and the driver (the forecast band/direction). "
            "Procurement/inventory only — no factory routing.\n\n"
            f"Decision: {decision}"
        )
        msg = client.chat.completions.create(
            model=config.FEATHERLESS_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4, max_tokens=120,
        )
        text = (msg.choices[0].message.content or "").strip()
        return text or _fallback_message(decision)
    except Exception as e:  # noqa: BLE001 — demo stability
        print(f"[safety_stock] narration failed, using fallback: {e}")
        return _fallback_message(decision)


def decide_and_narrate(asset, current_price, band_width, direction, confidence=None) -> dict:
    d = decide(asset, current_price, band_width, direction, confidence)
    d["message"] = narrate(d)
    return d


if __name__ == "__main__":
    import json
    print(json.dumps(decide_and_narrate("Gallium", 425.0, 0.45, "UP", 76), indent=2))
    print(json.dumps(decide_and_narrate("Copper", 11785.0, 0.15, "DOWN", 41), indent=2))
