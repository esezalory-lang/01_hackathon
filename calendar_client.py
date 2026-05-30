"""
calendar_client.py — live economic calendar (Myfxbook substitute).

Myfxbook has no clean free API, so we use the free ForexFactory feed mirrored by
faireconomy (no key). It returns this week's events with per-currency impact,
which Layer 1 uses to decide which pairs are in play.
"""
import requests

FF_THISWEEK = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Minimal offline fallback so Layer 1 still has macro context without network.
_FALLBACK = [
    {"currency": "USD", "title": "FOMC Rate Decision", "impact": "High"},
    {"currency": "EUR", "title": "ECB Main Refinancing Rate", "impact": "High"},
    {"currency": "EUR", "title": "German Flash CPI", "impact": "High"},
    {"currency": "JPY", "title": "BOJ Policy Rate", "impact": "High"},
    {"currency": "CNY", "title": "China Manufacturing PMI", "impact": "Medium"},
]


def get_calendar():
    """Return [{currency, title, impact, date}] for the week (or fallback)."""
    try:
        r = requests.get(FF_THISWEEK, timeout=20)
        r.raise_for_status()
        events = []
        for e in r.json():
            events.append({
                "currency": e.get("country"),   # feed uses ISO currency in 'country'
                "title": e.get("title"),
                "impact": e.get("impact"),
                "date": e.get("date"),
            })
        return events or _FALLBACK
    except Exception as e:  # noqa: BLE001
        print(f"[calendar_client] live fetch failed, using fallback: {e}")
        return _FALLBACK


def high_impact_by_currency(events=None):
    """Summarize High/Medium-impact events grouped by currency (for the prompt)."""
    events = events or get_calendar()
    summary = {}
    for e in events:
        if e.get("impact") not in ("High", "Medium"):
            continue
        cur = e.get("currency")
        if not cur:
            continue
        summary.setdefault(cur, [])
        if e["title"] and e["title"] not in summary[cur]:
            summary[cur].append(e["title"])
    return summary


if __name__ == "__main__":
    import json
    print(json.dumps(high_impact_by_currency(), indent=2))
