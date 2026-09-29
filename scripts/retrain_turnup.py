#!/usr/bin/env python3
"""Run a controlled time-split retraining job and write a manifest."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/processed/turnup_labelled_30min.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/processed"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "scripts/train_turnup_model.py", "--data", str(args.data), "--output", str(args.output)]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    metrics_path = args.output / "model_metrics.json"
    metadata_path = args.output / "feature_metadata.json"
    manifest = {
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "data": str(args.data),
        "metrics": str(metrics_path),
        "metadata": str(metadata_path),
        "command": command,
        "stdout": completed.stdout.strip().splitlines(),
        "status": "completed",
    }
    (args.output / "retraining_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
