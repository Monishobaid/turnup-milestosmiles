"""Safe workload dispatch connectors.

All connectors default to dry-run. A live connector must be explicitly
configured with TURNUP_DISPATCH_MODE=live and its provider endpoint/token.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class DispatchReceipt:
    connector: str
    mode: str
    accepted: bool
    detail: str


class WorkloadConnector:
    name = "base"

    def dispatch(self, assignments: list[dict[str, Any]]) -> DispatchReceipt:
        raise NotImplementedError


class DryRunConnector(WorkloadConnector):
    name = "dry-run"

    def dispatch(self, assignments: list[dict[str, Any]]) -> DispatchReceipt:
        return DispatchReceipt(self.name, "dry-run", True, f"validated {len(assignments)} assignments; no workload was started")


class WebhookConnector(WorkloadConnector):
    def __init__(self, name: str, url_env: str, token_env: str):
        self.name = name
        self.url = os.getenv(url_env)
        self.token = os.getenv(token_env)

    def dispatch(self, assignments: list[dict[str, Any]]) -> DispatchReceipt:
        if os.getenv("TURNUP_DISPATCH_MODE", "dry-run").lower() != "live":
            return DryRunConnector().dispatch(assignments)
        if not self.url or not self.token:
            raise RuntimeError(f"{self.name} live dispatch requires its endpoint and token environment variables")
        payload = json.dumps({"assignments": assignments}).encode("utf-8")
        request = urllib.request.Request(self.url, data=payload, method="POST", headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - operator-configured endpoint.
            return DispatchReceipt(self.name, "live", 200 <= response.status < 300, f"provider returned HTTP {response.status}")


class KubernetesConnector(WebhookConnector):
    def __init__(self):
        super().__init__("kubernetes", "TURNUP_KUBERNETES_WEBHOOK_URL", "TURNUP_KUBERNETES_TOKEN")


class AzureBatchConnector(WebhookConnector):
    def __init__(self):
        super().__init__("azure-batch", "TURNUP_AZURE_BATCH_WEBHOOK_URL", "TURNUP_AZURE_BATCH_TOKEN")


class SlurmConnector(WebhookConnector):
    def __init__(self):
        super().__init__("slurm", "TURNUP_SLURM_WEBHOOK_URL", "TURNUP_SLURM_TOKEN")


def connector_for(name: str) -> WorkloadConnector:
    return {"kubernetes": KubernetesConnector, "azure-batch": AzureBatchConnector, "slurm": SlurmConnector}.get(name, DryRunConnector)()
