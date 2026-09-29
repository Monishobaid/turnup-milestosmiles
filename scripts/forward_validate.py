#!/usr/bin/env python3
"""Evaluate predictions in chronological forward windows with no shuffling."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, mean_absolute_error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, default=Path("data/processed/predictions_test.csv"))
    parser.add_argument("--labels", type=Path, default=Path("data/processed/turnup_labelled_30min.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/forward_validation_report.json"))
    args = parser.parse_args()
    predictions = pd.read_csv(args.predictions, parse_dates=["timestamp_utc"])
    labels = pd.read_csv(args.labels, usecols=["timestamp_utc", "system_curtailment_mwh"], parse_dates=["timestamp_utc"]).rename(columns={"system_curtailment_mwh": "observed_curtailment_mwh"})
    joined = predictions.merge(labels, on="timestamp_utc", how="inner")
    joined["window"] = joined.timestamp_utc.dt.strftime("%Y-%m")
    windows = []
    for window, group in joined.groupby("window", sort=True):
        event = (group.observed_curtailment_mwh > 0.01).astype(int)
        windows.append({"window": window, "rows": int(len(group)), "event_rate": round(float(event.mean()), 5), "pr_auc": round(float(average_precision_score(event, group.model_event_probability)), 5) if event.nunique() > 1 else None, "brier": round(float(brier_score_loss(event, group.model_event_probability)), 5), "magnitude_mae_mwh": round(float(mean_absolute_error(group.observed_curtailment_mwh, group.model_expected_curtailment_mwh)), 5)})
    report = {"method": "chronological monthly windows; no shuffling; predictions are scored only against later observed labels", "windows": windows, "rows": int(len(joined))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
