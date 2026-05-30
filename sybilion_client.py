"""
sybilion_client.py — REAL Sybilion API client (confirmed request schema).

Your API key is read from config (which reads .env) — you never touch this file
to add credentials. Mirrors mock_sybilion.get_forecast() so app.py swaps one import.

Flow: submit (POST /forecasts) -> poll (GET /forecasts/:id) -> pull forecast.json.
The only TODO is the field names INSIDE forecast.json — fill _normalize() after
your first real job prints the artifact.
"""
import time, requests
import config

HEADERS = {"Authorization": f"Bearer {config.SYBILION_API_KEY}",
           "Content-Type": "application/json"}


def _to_timeseries(series):
    """series: list of ('YYYY-MM-01', value) -> the month-aligned map the API wants."""
    return {d: float(v) for d, v in series}


def submit(series, title, description, keywords, soft_horizon=6, backtest=True,
           categories=None, regions=None):
    ts = _to_timeseries(series)
    need = 40 if soft_horizon <= 3 else 60 if soft_horizon <= 6 else 120
    assert len(ts) >= need, f"need >={need} monthly points for horizon {soft_horizon}, have {len(ts)}"
    payload = {
        "pipeline_version": "v1",
        "frequency": "monthly",
        "soft_horizon": soft_horizon,
        "backtest": backtest,
        "timeseries": ts,
        "timeseries_metadata": {"title": title, "description": description,
                                "keywords": keywords[:20]},
    }
    if categories or regions:
        payload["filters"] = {"categories": categories, "regions": regions}
    r = requests.post(f"{config.SYBILION_BASE_URL}/api/v1/forecasts",
                      headers=HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def poll(job_id, timeout_s=300):
    waited = 0
    while waited < timeout_s:
        r = requests.get(f"{config.SYBILION_BASE_URL}/api/v1/forecasts/{job_id}",
                         headers=HEADERS, timeout=30)
        r.raise_for_status()
        status = r.json().get("status")
        if status == "completed":
            return r.json()
        if status == "failed":
            raise RuntimeError(f"forecast failed: {r.json()}")
        time.sleep(30); waited += 30
    raise TimeoutError("forecast did not complete in time")


def _artifact(job_id, name):
    r = requests.get(f"{config.SYBILION_BASE_URL}/api/v1/forecasts/{job_id}/artifacts/{name}",
                     headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def _normalize(forecast_json, horizon):
    # TODO: map forecast.json fields onto the engine's internal shape after you
    # see one real artifact (run a job and print it). Adjust the right-hand sides.
    return {
        "current_price": forecast_json["last_actual"],                       # <- TODO confirm
        "horizon_months": horizon,
        "bands": [{"month": i + 1, "p10": p["p10"], "p50": p["p50"], "p90": p["p90"]}
                  for i, p in enumerate(forecast_json["forecast"])],         # <- TODO confirm
        "drivers": forecast_json.get("drivers", []),                        # <- TODO confirm
        "backtest": forecast_json.get("backtest", {}),
    }


def get_forecast(series, keywords, horizon_months=6, title=None, description=None):
    d = config.ACTIVE_DOMAIN
    job = submit(series, title or d["title"], description or d["description"],
                 keywords or d["keywords"], soft_horizon=horizon_months)
    poll(job)
    return _normalize(_artifact(job, "forecast.json"), horizon_months)


if __name__ == "__main__":
    assert config.SYBILION_API_KEY, "set SYBILION_API_KEY in .env first"
    print("client ready — call get_forecast(series, keywords)")
