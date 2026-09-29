#!/usr/bin/env python3
"""Join held-out TURNUP model predictions to the audited EirGrid features."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, default=Path("data/processed/predictions_test.csv"))
    parser.add_argument("--labels", type=Path, default=Path("data/processed/turnup_labelled_30min.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/turnup_scored_30min.csv"))
    args = parser.parse_args()

    predictions = pd.read_csv(args.predictions, parse_dates=["timestamp_utc"])
    labels = pd.read_csv(args.labels, parse_dates=["timestamp_utc"])
    scored = labels.merge(
        predictions.drop(columns=["system_curtailment_mwh", "event"], errors="ignore"),
        on="timestamp_utc",
        how="inner",
        validate="one_to_one",
    ).sort_values("timestamp_utc")
    if scored.empty:
        raise RuntimeError("No prediction timestamps matched audited labels")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    scored.to_csv(args.output, index=False)
    print(f"rows={len(scored)} min={scored.timestamp_utc.min().isoformat()} max={scored.timestamp_utc.max().isoformat()}")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
