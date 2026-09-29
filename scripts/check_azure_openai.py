#!/usr/bin/env python3
"""Verify TURNUP's server-side Azure OpenAI configuration without printing the key."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    if not endpoint or not api_key:
        print("Azure OpenAI configuration is incomplete: set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY in .env", file=sys.stderr)
        return 2
    url = f"{endpoint}/openai/models?api-version=2024-10-21"
    request = urllib.request.Request(url, headers={"api-key": api_key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        print(f"Azure OpenAI check failed with HTTP {error.code}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError) as error:
        print(f"Azure OpenAI check could not connect: {error}", file=sys.stderr)
        return 1
    model_ids = [item.get("id") for item in payload.get("data", []) if item.get("id")]
    print(f"Azure OpenAI endpoint reachable: {endpoint}")
    print(f"Models visible to this key: {len(model_ids)}")
    print("Model ids: " + ", ".join(model_ids[:20]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
