#!/usr/bin/env python3
"""Compute prediction quality and simple feature-drift monitoring metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, mean_absolute_error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, default=Path("data/processed/predictions_test.csv"))
    parser.add_argument("--labels", type=Path, default=Path("data/processed/turnup_labelled_30min.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/monitoring_report.json"))
    args = parser.parse_args()
    predictions = pd.read_csv(args.predictions, parse_dates=["timestamp_utc"])
    labels = pd.read_csv(args.labels, usecols=["timestamp_utc", "system_curtailment_mwh"], parse_dates=["timestamp_utc"])
    joined = predictions.merge(labels, on="timestamp_utc", how="inner", suffixes=("_prediction", "_observed"))
    if joined.empty:
        raise RuntimeError("No prediction/label timestamps matched")
    observed_event = (joined.system_curtailment_mwh_observed > 0.01).astype(int)
    probability = joined.model_event_probability.clip(0, 1)
    report = {
        "rows": int(len(joined)),
        "time_range": {"min": joined.timestamp_utc.min().isoformat(), "max": joined.timestamp_utc.max().isoformat()},
        "quality": {
            "pr_auc": round(float(average_precision_score(observed_event, probability)), 5),
            "brier": round(float(brier_score_loss(observed_event, probability)), 5),
            "magnitude_mae_mwh": round(float(mean_absolute_error(joined.system_curtailment_mwh_observed, joined.model_expected_curtailment_mwh)), 5),
            "observed_event_rate": round(float(observed_event.mean()), 5),
        },
        "drift": {},
    }
    for column in ["model_event_probability", "model_expected_curtailment_mwh"]:
        values = joined[column].astype(float).to_numpy()
        report["drift"][column] = {"mean": round(float(np.mean(values)), 5), "std": round(float(np.std(values)), 5), "p95": round(float(np.quantile(values, .95)), 5)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
