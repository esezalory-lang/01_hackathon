"""
explain.py — the LLM's ONLY job: turn the engine's structured decision into
plain words. It does NOT decide anything. If no Featherless key is set, a
template fallback produces a clean explanation so the pipeline never blocks.

Friday: set FEATHERLESS_API_KEY (or your HF token) to use a real model.
"""
import config


def explain(decision, delta=None):
    """decision: dict from decide(). delta: optional diff_decisions() output."""
    key = config.FEATHERLESS_API_KEY
    if key:
        try:
            return _llm_explain(decision, delta, key)
        except Exception as e:
            return _template_explain(decision, delta) + f"\n(LLM unavailable: {e})"
    return _template_explain(decision, delta)


def _template_explain(decision, delta):
    d = decision
    drv = d.get("top_driver")
    drv_txt = f" Main driver: {drv['name']} (importance {drv['importance']} at {drv['horizon_months']}mo)." if drv else ""
    base = (f"Recommendation: {d['action']} (confidence {d['confidence']}). "
            f"Expected saving from waiting {d['expected_saving_pct']}%, "
            f"upside price risk {d['downside_risk_pct']}%, "
            f"uncertainty {d['band_width_pct']}%.{drv_txt} "
            f"Reasoning: {'; '.join(d['rationale'])}.")
    if delta and delta.get("flipped"):
        base += " ASSUMPTION CHANGED -> recommendation flipped. " + \
                "; ".join(f"{k}: {v['from']} -> {v['to']}" for k, v in delta["changes"].items())
    return base


def _llm_explain(decision, delta, key):
    # Featherless is OpenAI-compatible. Keep the model's role to NARRATION only.
    from openai import OpenAI
    client = OpenAI(base_url="https://api.featherless.ai/v1", api_key=key)
    prompt = ("You narrate a procurement decision in 2-3 sentences for a manager. "
              "Do NOT change or second-guess the decision; only explain it clearly. "
              f"Decision object: {decision}. Change since last run: {delta}.")
    resp = client.chat.completions.create(
        model="Qwen/Qwen2.5-7B-Instruct",   # confirm exact name in Featherless catalog
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
    )
    return resp.choices[0].message.content.strip()


if __name__ == "__main__":
    from mock_sybilion import get_forecast
    from decision_engine import decide
    fc = get_forecast([100, 101, 102, 103, 104, 105], ["China demand", "mine supply"], 6)
    print(explain(decide(fc, decision_horizon=3)))
