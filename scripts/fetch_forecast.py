#!/usr/bin/env python3
"""Fetch and validate a configured official forecast feed.

The provider URL is intentionally operator supplied: EirGrid/provider access
and licensing vary by deployment. The script never substitutes actuals when a
provider is unavailable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from turnup.forecast import configured_forecast


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="HTTP(S) JSON/CSV endpoint or local CSV path")
    parser.add_argument("--output", type=Path, default=Path("data/processed/forecast_latest.json"))
    args = parser.parse_args()
    intervals = configured_forecast(args.url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps([item.as_dict() for item in intervals], indent=2) + "\n")
    print(f"validated {len(intervals)} forecast intervals from {intervals[0].source}")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
