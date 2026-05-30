"""
sybilion_client.py — REAL Sybilion API client (FX pairs).

Mirrors mock_sybilion so step2 swaps mock<->real by flipping config.USE_MOCK:

    forecast_pair(pair_meta, timeseries, current_price, shock=None) -> D2 dict

`timeseries` is the monthly map built upstream (FRED history + hourly current
month). We submit with filters.limit=0 (NO external drivers) and a 3-month
horizon, poll, read forecast.json, and normalize to the same shape as the mock:

    {pair, slug, fred_id, quote, current_price, forecast[{month,p10,p50,p90}],
     drivers[], backtest{mape,baseline_mape}, source}
"""
import time

import requests

import config

HEADERS = {
    "Authorization": f"Bearer {config.SYBILION_API_KEY}",
    "Content-Type": "application/json",
}


def submit(timeseries, title, description, keywords=None,
           soft_horizon=None, backtest=True, driver_limit=None):
    soft_horizon = soft_horizon or config.SOFT_HORIZON
    driver_limit = config.SYBILION_DRIVER_LIMIT if driver_limit is None else driver_limit
    need = 40 if soft_horizon <= 3 else 60 if soft_horizon <= 6 else 120
    assert len(timeseries) >= need, (
        f"need >={need} monthly points for horizon {soft_horizon}, have {len(timeseries)}")
    payload = {
        "pipeline_version": "v1",
        "frequency": "monthly",
        "soft_horizon": soft_horizon,
        "backtest": backtest,
        "timeseries": timeseries,
        "timeseries_metadata": {
            "title": title,
            "description": description,
            "keywords": (keywords or [])[:20],
        },
        "filters": {"limit": driver_limit},   # 0 -> no external driver datasets
    }
    r = requests.post(f"{config.SYBILION_BASE_URL}/api/v1/forecasts",
                      headers=HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    body = r.json()
    return body.get("id") or body.get("job_id")


def poll(job_id, timeout_s=600, interval_s=30):
    waited = 0
    while waited < timeout_s:
        r = requests.get(f"{config.SYBILION_BASE_URL}/api/v1/forecasts/{job_id}",
                         headers=HEADERS, timeout=30)
        r.raise_for_status()
        body = r.json()
        status = body.get("status")
        if status == "completed":
            return body
        if status == "failed":
            raise RuntimeError(f"forecast failed: {body}")
        time.sleep(interval_s)
        waited += interval_s
    raise TimeoutError("forecast did not complete in time")


def read_artifacts(job_id, name):
    """GET one JSON artifact (forecast.json, backtest_metrics.json, ...)."""
    r = requests.get(
        f"{config.SYBILION_BASE_URL}/api/v1/forecasts/{job_id}/artifacts/{name}",
        headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def _q(quantiles, key, default=None):
    for k in (key, key.rstrip("0").rstrip("."), f"{float(key):.2f}"):
        if k in quantiles:
            return quantiles[k]
    return default


def _normalize(pair_meta, forecast_json, current_price, metrics_json=None):
    """Map forecast.json -> D2 (p10/p50/p90 per month)."""
    data = forecast_json.get("data", forecast_json)
    series = data.get("forecast_series", {})
    bands = []
    for i, (_date, point) in enumerate(sorted(series.items()), start=1):
        q = point.get("quantile_forecast", {})
        p50 = point.get("forecast", _q(q, "0.50"))
        bands.append({"month": i, "p10": _q(q, "0.10", p50), "p50": p50,
                      "p90": _q(q, "0.90", p50)})

    backtest = {}
    if metrics_json:
        backtest = {
            "mape": metrics_json.get("mape") or metrics_json.get("MAPE"),
            "baseline_mape": metrics_json.get("baseline_mape") or metrics_json.get("naive_mape"),
        }

    return {
        "pair": pair_meta["pair"],
        "slug": pair_meta["slug"],
        "fred_id": pair_meta.get("fred_id"),
        "quote": pair_meta.get("quote"),
        "current_price": current_price,
        "forecast": bands,
        "drivers": [],            # filters.limit=0 -> no external drivers
        "backtest": backtest,
        "source": "sybilion",
    }


def forecast_pair(pair_meta, timeseries, current_price=None, shock=None):
    """Submit one pair's monthly series to Sybilion and return its D2 forecast."""
    if current_price is None and timeseries:
        current_price = timeseries[sorted(timeseries)[-1]]
    title = f"{pair_meta['pair']} monthly exchange rate ({pair_meta.get('quote', '')})".strip()
    description = (f"Monthly average {pair_meta['pair']} exchange rate from FRED series "
                  f"{pair_meta.get('fred_id')}, current month refreshed from an hourly feed.")
    job_id = submit(timeseries, title=title, description=description,
                    soft_horizon=config.SOFT_HORIZON, backtest=True,
                    driver_limit=config.SYBILION_DRIVER_LIMIT)
    poll(job_id)
    forecast_json = read_artifacts(job_id, "forecast.json")
    metrics_json = None
    try:
        metrics_json = read_artifacts(job_id, "backtest_metrics.json")
    except Exception:
        pass
    return _normalize(pair_meta, forecast_json, current_price, metrics_json)


if __name__ == "__main__":
    assert config.SYBILION_API_KEY, "set SYBILION_API_KEY in .env first"
    print("client ready — call forecast_pair(pair_meta, timeseries)")
