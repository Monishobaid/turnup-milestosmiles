#!/usr/bin/env python3
"""Attach explicit site/grid location fields to scored intervals."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/processed/turnup_scored_30min.csv"))
    parser.add_argument("--locations", type=Path, default=Path("data/site_locations.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/turnup_scored_locational_30min.csv"))
    parser.add_argument("--site-id", default="milestosmiles-demo")
    args = parser.parse_args()
    data = pd.read_csv(args.input)
    locations = pd.read_csv(args.locations)
    selected = locations[locations.site_id.eq(args.site_id)]
    if len(selected) != 1:
        raise RuntimeError(f"Expected exactly one location row for {args.site_id}")
    for column, value in selected.iloc[0].items():
        data[column] = value
    args.output.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(args.output, index=False)
    print(f"rows={len(data)} site_id={args.site_id} location_status={selected.iloc[0]['location_status']}")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
