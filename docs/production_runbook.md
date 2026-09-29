# TURNUP production runbook

## Forecast input

The approved provider must return JSON or CSV rows with:

```text
timestamp_utc,load_forecast_mw,wind_forecast_mw,solar_forecast_mw,
price_forecast_eur_per_mwh,constraint_region,grid_node
```

Set `TURNUP_FORECAST_URL` and, if required, `TURNUP_FORECAST_TOKEN`, then run:

```bash
work/turnup-venv/bin/python scripts/fetch_forecast.py
```

The adapter rejects missing timezones, duplicate timestamps, non-numeric values and empty feeds.

## Model operations

Run retraining in an isolated output directory first:

```bash
work/turnup-venv/bin/python scripts/retrain_turnup.py \
  --output data/processed/retraining-$(date +%Y%m%d)
```

Run monitoring after predictions can be joined to observed labels:

```bash
work/turnup-venv/bin/python scripts/monitor_turnup.py
work/turnup-venv/bin/python scripts/forward_validate.py
```

Promote a model only after the quality, drift and forward-window reports have been reviewed.

## Authenticated API

The API refuses to start without `TURNUP_API_TOKEN`:

```bash
TURNUP_API_TOKEN='stored-in-a-secret-manager' \
  work/turnup-venv/bin/python scripts/run_api.py --host 127.0.0.1 --port 8090
```

`GET /health` is unauthenticated. `POST /v1/schedule` and `POST /v1/dispatch` require:

```text
Authorization: Bearer <TURNUP_API_TOKEN>
```

The schedule payload contains `intervals`, `jobs` and `site_capacity_mw`. Interval rows contain `expected_curtailment_mwh`, `event_probability`, `price_eur_per_mwh`, `baseline_mw` and optionally `site_capacity_mw`. Job rows contain `job_id`, `energy_mwh`, `max_power_mw`, `earliest_slot`, `deadline_slot` and `job_type`.

## Workload dispatch safety

Dispatch defaults to dry-run. Set `TURNUP_DISPATCH_MODE=live` only after the workload owner approves the connector endpoint and token. Kubernetes, Azure Batch and Slurm are represented as webhook adapters so the provider-specific authentication and idempotency contract can be reviewed before live execution.

## Location data

Replace the `placeholder_for_team_site` row in `data/site_locations.csv` with the actual site, constraint region and grid node. Do not use the demo mapping for a local-constraint claim.
