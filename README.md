# TURNUP — MilestoSmiles

Curtailment-aware scheduling for flexible electricity demand.

TURNUP is the MilestoSmiles prototype for Hack the Climate. It forecasts **system-wide renewable-curtailment opportunities** and moves already-planned, flexible workloads into those windows without changing total energy, breaking deadlines, or exceeding a site's import capacity.

The current build is a dependency-free browser prototype with a deterministic, explainable scheduler. The public Hack the Climate Ireland feeds and EirGrid Wind/IE dispatch-down labels are now audited and joined into a canonical 30-minute dataset; the synthetic data remains available as a fallback.

Azure OpenAI configuration belongs in the ignored `.env` file (`AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_API_KEY`). The key is never embedded in browser JavaScript or committed data. A deployment name is still required before adding model calls; the static dashboard does not send the key to the browser.

Check the server-side configuration with:

```bash
python3 scripts/check_azure_openai.py
```

## Run it

From this directory:

```bash
python3 -m http.server 8000
```

Open <http://localhost:8000> and use **Load audited EirGrid join** to load the labelled intervals. The same dataset can be selected with the file picker.

The app is plain HTML, CSS and JavaScript, so it can also be copied to the team VM and served with any static web server.

## What is in the MVP

- A 24-hour, 30-minute grid horizon with renewable generation, load, price and system-curtailment opportunity signals.
- A transparent opportunity score that combines renewable share, residual load, price and the expected curtailment signal.
- A greedy deterministic scheduler for an existing portfolio of flexible AI/data-centre workloads.
- Constraints for job energy, earliest start, deadline, max power, baseline site load and import capacity.
- Before/after energy, peak and deadline-preservation KPIs.
- An explanation panel that shows why the selected slots were preferred.
- A canonical CSV import path for the Hack the Climate data shape.
- A reproducible historical heuristic and leakage-safe two-stage baseline model.
- Formal workload and site-baseline inputs in `data/workloads.csv` and `data/site_baseline.csv`.

## Product guardrails

TURNUP targets system-wide curtailment first. It does not claim to resolve local network constraints, market-driven shutdowns, or all Irish dispatch-down. The impact number in this prototype is labelled **potentially absorbable renewable energy under simulation**, not guaranteed physical renewable energy saved.

The model-facing data contract is one row per 30-minute interval:

```text
timestamp_utc,timestamp_local,load_actual_mw,load_forecast_mw,
wind_actual_mw,wind_forecast_mw,solar_actual_mw,solar_forecast_mw,
price_eur_per_mwh,system_curtailment_mwh,local_constraint_mwh,
total_dispatch_down_mwh
```

Actual future values must not be used as day-ahead features. When real data is wired in, add time-safe lag/rolling features and keep system curtailment separate from local constraints.

## Connected data and audit

The source archive is downloaded from the official Hack the Climate page and the EirGrid workbooks are downloaded from EirGrid's System and Renewable Data Reports page. The raw archive is kept locally under `data/raw`; only the Ireland extracts are unpacked for the join.

```bash
work/turnup-venv/bin/python scripts/audit_data.py
```

This writes:

- `data/processed/turnup_30min.csv` — the full Ireland 30-minute contract.
- `data/processed/turnup_labelled_30min.csv` — rows with an EirGrid Wind + IE label.
- `data/processed/audit_report.json` — source ranges, duplicates/gaps, join coverage and label interpretation.

The current audit covers 107,998 canonical intervals and 24,270 intervals with EirGrid labels (2025-01-01 through 2026-06-30 in the overlapping Hack the Climate range). `system_curtailment_mwh` is EirGrid `CURTAILMENTS_MWH`; `local_constraint_mwh` is `CONSTRAINTS_MWH`; they are intentionally not collapsed.

## Phase 2–4 status

`scripts/train_turnup_model.py` now creates past-only lag/rolling features, a transparent historical surplus-opportunity score, and a two-stage baseline: logistic event probability plus gradient-boosted conditional magnitude. The split is chronological (65% train, 15% validation, 20% test); no current-interval actuals or labels are used as model features.

Current held-out test artifacts:

- `data/processed/model_metrics.json` — PR-AUC, calibration, Brier score, top-decile recall/lift and magnitude MAE.
- `data/processed/predictions_test.csv` — per-interval model and heuristic predictions.
- `data/processed/feature_metadata.json` — feature safety and time-split provenance.
- `data/processed/models/` — locally saved event and magnitude models.

The first historical simulation reports model PR-AUC **0.78523** versus heuristic **0.70948**, with model top-decile recall **0.33998** versus **0.30008**. These are historical backtest results, not a day-ahead production claim; published forecasts still need to replace actual-derived inputs.

## Phase 5–6 schedule evaluation and optimiser connection

The held-out model predictions are joined back to the audited EirGrid features with:

```bash
work/turnup-venv/bin/python scripts/build_scored_dataset.py
```

`data/processed/turnup_scored_30min.csv` is the dashboard-facing scored contract. The browser importer prefers `model_event_probability`, `model_expected_curtailment_mwh` and `heuristic_opportunity_score` when present, so the deterministic optimiser ranks windows using the TURNUP model signal while retaining price, baseline, capacity and deadline guardrails. The API key remains server-side and is not needed by the static optimiser.

The reproducible schedule comparison is:

```bash
work/turnup-venv/bin/python scripts/evaluate_schedules.py
```

It evaluates fixed, price-only, TURNUP and oracle policies on the 84 complete held-out days (17 incomplete days are excluded). Outputs are `data/processed/schedule_daily_comparison.csv`, `data/processed/schedule_assignments.csv` and `data/processed/schedule_metrics.json`. All policies deliver the same 3,192 MWh workload target with zero deadline misses and zero capacity violations. The oracle is an upper bound because it sees actual curtailment; TURNUP uses only model predictions.

Current aggregate results:

| policy | curtailment overlap | incremental vs fixed | mean cost/day | max peak |
| --- | ---: | ---: | ---: | ---: |
| fixed | 797.49 MWh | 0.00 MWh | €4,214.01 | 19.60 MW |
| price-only | 1,015.58 MWh | 218.09 MWh | €3,667.50 | 19.60 MW |
| TURNUP | 1,009.59 MWh | 212.10 MWh | €3,853.54 | 19.60 MW |
| oracle | 1,190.73 MWh | 393.24 MWh | €4,010.67 | 19.60 MW |

These are historical simulation results, not a claim that all overlap becomes physically saved renewable energy.

## Production foundations (requested items 1–7)

The repository now includes safe-by-default foundations for the next deployment stage:

1. `turnup/forecast.py` and `scripts/fetch_forecast.py` validate operator-configured official JSON/CSV forecast feeds. They require forecast columns and never silently substitute same-interval actuals. Set `TURNUP_FORECAST_URL` (and, if needed, `TURNUP_FORECAST_TOKEN`) when the approved EirGrid/provider endpoint is available.
2. `scripts/retrain_turnup.py` runs a reproducible time-split retraining job and writes a manifest. `scripts/monitor_turnup.py` writes prediction-quality and drift metrics; `scripts/forward_validate.py` reports chronological monthly performance against later labels.
3. `turnup/solver.py` is a SciPy mixed-integer optimiser. It preserves exact workload energy, deadlines, site capacity and contiguous runs for continuous jobs. The browser greedy scheduler remains the demo surface; the API below uses this solver.
4. `turnup/connectors.py` provides dry-run, Kubernetes, Azure Batch and Slurm dispatch connectors. Live dispatch requires `TURNUP_DISPATCH_MODE=live` plus an explicitly configured provider webhook and token.
5. `turnup/api.py` and `scripts/run_api.py` provide a dependency-light HTTP API. `/health` is public; scheduling and dispatch endpoints require a bearer token in `TURNUP_API_TOKEN`.
6. `data/site_locations.csv` and `scripts/enrich_locations.py` add explicit `site_id`, `constraint_region`, `grid_node` and coordinates. The included row is a clearly marked demo placeholder, not a claim about the team's final site.
7. `scripts/forward_validate.py` produces `data/processed/forward_validation_report.json` using chronological windows and observed labels; this is the bridge to future operational validation.

Example commands:

```bash
work/turnup-venv/bin/python scripts/monitor_turnup.py
work/turnup-venv/bin/python scripts/forward_validate.py
TURNUP_API_TOKEN='use-a-secret-from-your-deployment-manager' \
  work/turnup-venv/bin/python scripts/run_api.py --port 8090
```

The external feed URL, real site location, workload platform credentials and production deployment are intentionally not guessed or embedded. They are the remaining activation work.

## Next implementation steps

1. Configure the approved official forecast endpoint and confirm its licensing, cadence and authentication.
2. Deploy the authenticated API behind TLS and a secret manager; keep dispatch in dry-run until workload owners approve it.
3. Replace the demo location row with the team's actual site/grid mapping.
4. Connect one real workload platform and test cancellation, retries and idempotency.
5. Run forward validation on newly arriving operational data and set alert thresholds for drift.
6. Add one selected Azure OpenAI deployment for explanation summaries; keep the solver deterministic.

## Repository layout

```text
index.html   product surface and accessible controls
styles.css   responsive visual system
app.js       demo data, opportunity score, scheduler and rendering
scripts/audit_data.py  reproducible Hack the Climate + EirGrid join
scripts/train_turnup_model.py  heuristic + time-split two-stage baseline
scripts/build_scored_dataset.py  join model predictions to audited features
scripts/evaluate_schedules.py  fixed/price/TURNUP/oracle comparison
scripts/fetch_forecast.py  validate configured forecast feeds
scripts/retrain_turnup.py  controlled model retraining
scripts/monitor_turnup.py  quality and drift monitoring
scripts/forward_validate.py  chronological forward validation
scripts/run_api.py  authenticated scheduling API
turnup/solver.py  production mixed-integer optimiser
turnup/connectors.py  dry-run/Kubernetes/Azure Batch/Slurm adapters
data/site_locations.csv  explicit location schema and demo mapping
docs/production_runbook.md  feed, operations, API and dispatch runbook
docs/deployment_status.md  current VM presentation URL and activation blockers
data/processed/        canonical CSVs and audit report
data/workloads.csv     Phase 4 flexible workload portfolio
data/site_baseline.csv Phase 4 baseline and import-capacity profile
README.md    scope, setup and modelling guardrails
```

Team: **MilestoSmiles**  
Product: **TURNUP**

## Team 09 VM helper

The repository includes [`scripts/setup_hack_vm.sh`](scripts/setup_hack_vm.sh), configured for the team 09 resources from the hackathon instructions:

```bash
./scripts/setup_hack_vm.sh
```

It starts device-code login automatically when needed, checks the active subscription and `rg-hack-team09-swc`, then runs `az ssh vm` for `vm-hack-team09`. It does not print or retrieve Key Vault secrets. The helper prefers a global `az` already authenticated in your shell; otherwise it uses the isolated Azure CLI at `work/azure-cli-venv/bin/az` and stores its local CLI state under `work/azure-config`.

If Azure CLI is not on a shell PATH, invoke the isolated CLI directly with:

```bash
AZURE_CONFIG_DIR="$PWD/work/azure-config" work/azure-cli-venv/bin/az login --use-device-code
```
