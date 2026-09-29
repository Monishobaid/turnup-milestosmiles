"""Safe adapters for official forecast feeds and local forecast files.

The adapter deliberately accepts forecasts only. It never turns same-interval
actual measurements into a forecast, which keeps the deployment contract
separate from the historical backtest.
"""

from __future__ import annotations

import csv
import io
import json
import os
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ForecastInterval:
    timestamp_utc: str
    load_forecast_mw: float
    wind_forecast_mw: float
    solar_forecast_mw: float = 0.0
    price_forecast_eur_per_mwh: float | None = None
    constraint_region: str | None = None
    grid_node: str | None = None
    source: str = "configured-provider"
    issued_at_utc: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


REQUIRED = {"timestamp_utc", "load_forecast_mw", "wind_forecast_mw"}


def _number(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{field} must be finite")
    return result


def _timestamp(value: Any) -> str:
    text = str(value).strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamp_utc must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_rows(rows: list[dict[str, Any]], source: str, issued_at_utc: str | None = None) -> list[ForecastInterval]:
    if not rows:
        raise ValueError("forecast feed returned no rows")
    missing = REQUIRED - set(rows[0])
    if missing:
        raise ValueError(f"forecast feed missing columns: {sorted(missing)}")
    normalized: list[ForecastInterval] = []
    seen: set[str] = set()
    for row in rows:
        timestamp = _timestamp(row["timestamp_utc"])
        if timestamp in seen:
            raise ValueError(f"duplicate forecast timestamp: {timestamp}")
        seen.add(timestamp)
        normalized.append(ForecastInterval(
            timestamp_utc=timestamp,
            load_forecast_mw=_number(row["load_forecast_mw"], "load_forecast_mw"),
            wind_forecast_mw=max(0.0, _number(row["wind_forecast_mw"], "wind_forecast_mw")),
            solar_forecast_mw=max(0.0, _number(row.get("solar_forecast_mw", 0.0), "solar_forecast_mw")),
            price_forecast_eur_per_mwh=None if row.get("price_forecast_eur_per_mwh") in (None, "") else _number(row["price_forecast_eur_per_mwh"], "price_forecast_eur_per_mwh"),
            constraint_region=row.get("constraint_region") or None,
            grid_node=row.get("grid_node") or None,
            source=source,
            issued_at_utc=issued_at_utc,
        ))
    return sorted(normalized, key=lambda item: item.timestamp_utc)


def read_forecast_csv(path: Path, source: str | None = None) -> list[ForecastInterval]:
    with path.open(newline="", encoding="utf-8") as handle:
        return normalize_rows(list(csv.DictReader(handle)), source or str(path))


def read_forecast_json(payload: Any, source: str = "http-provider") -> list[ForecastInterval]:
    issued_at = None
    if isinstance(payload, dict):
        issued_at = payload.get("issued_at_utc")
        payload = payload.get("intervals", payload.get("data", payload))
    if not isinstance(payload, list):
        raise ValueError("JSON forecast must be a list or an object containing intervals")
    return normalize_rows(payload, source, issued_at)


def fetch_forecast(url: str, token: str | None = None, timeout_seconds: int = 30) -> list[ForecastInterval]:
    request = urllib.request.Request(url, headers={"Accept": "application/json, text/csv"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - URL is operator configured.
        body = response.read()
        content_type = response.headers.get("Content-Type", "")
    if "json" in content_type or body.lstrip().startswith((b"{", b"[")):
        return read_forecast_json(json.loads(body.decode("utf-8")), url)
    return normalize_rows(list(csv.DictReader(io.StringIO(body.decode("utf-8")))), url)


def configured_forecast(url: str | None = None) -> list[ForecastInterval]:
    """Load the configured provider without silently falling back to actuals."""
    path = url or os.getenv("TURNUP_FORECAST_URL")
    if not path:
        raise RuntimeError("Set TURNUP_FORECAST_URL or pass --url; no live forecast provider is configured")
    token = os.getenv("TURNUP_FORECAST_TOKEN")
    if path.startswith(("http://", "https://")):
        return fetch_forecast(path, token)
    return read_forecast_csv(Path(path), path)
