# TURNUP validation snapshot

Validated 29 September 2026 against the local MilestoSmiles dashboard and saved repository artifacts.

## Dashboard run

- Audited EirGrid join loaded: 96 intervals.
- Workload portfolio: 5 jobs, 38 MWh total.
- Jobs protected: 5/5.
- Site peak: 19.5 MW, below the 20.0 MW import limit.
- Dashboard result: 6.0 MWh potentially absorbable under simulation.
- The dashboard remains a historical/demo scheduler; it does not dispatch live workloads.

## Repository checks

- Held-out prediction rows: 4,778.
- Positive curtailment intervals: 1,253.
- Model PR-AUC: 0.78523.
- Magnitude MAE: 49.98421 MWh.
- Schedule comparison rows checked: 336.
- Every saved schedule row preserved 38.0 MWh, had zero unmet energy, zero deadline misses, zero capacity violations, and peak at or below 20 MW.

## Recording

`turnup-audited-backup.mp4` is a 60-second silent backup clip made from verified dashboard states: opening screen, audited schedule KPIs, decision trace, and protected workload table. It is a visual backup rather than a live mouse-and-voice capture.
