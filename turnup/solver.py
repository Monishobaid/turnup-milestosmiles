"""Constrained MILP scheduler for flexible workloads.

Power variables are continuous and on/off variables are binary. The model
preserves exact workload energy, deadlines and site import capacity. For a
continuous workload, on/off variables are constrained to one contiguous run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix


SLOT_HOURS = 0.5


def _continuous_slots(job: dict[str, Any]) -> int:
    return max(1, int(np.ceil(float(job["energy_mwh"]) / (float(job["max_power_mw"]) * SLOT_HOURS) - 1e-9)))


@dataclass(frozen=True)
class SolverResult:
    status: str
    objective: float
    assignments: list[dict[str, Any]]
    summary: dict[str, Any]


def solve_schedule(intervals: list[dict[str, Any]], jobs: list[dict[str, Any]], site_capacity_mw: float) -> SolverResult:
    if not intervals or not jobs:
        raise ValueError("intervals and jobs are required")
    slots = list(range(len(intervals)))
    power_keys = [(j, s) for j in range(len(jobs)) for s in slots if jobs[j]["earliest_slot"] <= s < jobs[j]["deadline_slot"]]
    on_keys = power_keys
    start_keys = [(j, s) for j, job in enumerate(jobs) if str(job.get("job_type", "interruptible")).lower() == "continuous" for s in slots if job["earliest_slot"] <= s <= job["deadline_slot"] - _continuous_slots(job)]
    keys = [("power", *key) for key in power_keys] + [("on", *key) for key in on_keys] + [("start", *key) for key in start_keys]
    index = {key: i for i, key in enumerate(keys)}
    n = len(keys)
    objective = np.zeros(n)
    lower = np.zeros(n)
    upper = np.full(n, np.inf)
    integrality = np.zeros(n)
    for key, i in index.items():
        kind, j, s = key
        job = jobs[j]
        if kind == "power":
            expected = float(intervals[s].get("expected_curtailment_mwh", 0.0))
            probability = float(intervals[s].get("event_probability", 0.0))
            price = float(intervals[s].get("price_eur_per_mwh", 0.0))
            urgency = float(intervals[s].get("urgency", 0.0))
            objective[i] = -(expected + 0.2 * probability + 0.05 * urgency - 0.002 * price) * SLOT_HOURS
            upper[i] = float(job["max_power_mw"])
        else:
            upper[i] = 1.0
            integrality[i] = 1
    rows: list[dict[int, float]] = []
    row_lb: list[float] = []
    row_ub: list[float] = []

    def add(values: dict[int, float], lb: float, ub: float) -> None:
        rows.append(values); row_lb.append(lb); row_ub.append(ub)

    for j, job in enumerate(jobs):
        add({index[("power", j, s)]: SLOT_HOURS for s in slots if ("power", j, s) in index}, float(job["energy_mwh"]), float(job["energy_mwh"]))
        for s in slots:
            if ("power", j, s) in index:
                add({index[("power", j, s)]: 1.0, index[("on", j, s)]: -float(job["max_power_mw"])}, -np.inf, 0.0)
        if str(job.get("job_type", "interruptible")).lower() == "continuous":
            starts = [index[("start", j, s)] for s in slots if ("start", j, s) in index]
            add({i: 1.0 for i in starts}, 1.0, 1.0)
            needed = _continuous_slots(job)
            for s in slots:
                if ("on", j, s) not in index:
                    continue
                active_starts = [index[("start", j, start)] for start in slots if ("start", j, start) in index and start <= s < start + needed]
                add({index[("on", j, s)]: 1.0, **{i: -1.0 for i in active_starts}}, 0.0, 0.0)
    for s, interval in enumerate(intervals):
        values = {index[("power", j, s)]: 1.0 for j in range(len(jobs)) if ("power", j, s) in index}
        baseline = float(interval.get("baseline_mw", 0.0))
        add(values, -np.inf, min(float(interval.get("site_capacity_mw", site_capacity_mw)), site_capacity_mw) - baseline)
    matrix = lil_matrix((len(rows), n), dtype=float)
    for r, values in enumerate(rows):
        for col, value in values.items():
            matrix[r, col] = value
    result = milp(c=objective, integrality=integrality, bounds=Bounds(lower, upper), constraints=LinearConstraint(matrix.tocsr(), np.array(row_lb), np.array(row_ub)), options={"time_limit": 30})
    if not result.success or result.x is None:
        raise RuntimeError(f"TURNUP optimiser failed: {result.message}")
    assignments: list[dict[str, Any]] = []
    for (kind, j, s), i in index.items():
        if kind == "power" and result.x[i] > 1e-6:
            assignments.append({"job_id": jobs[j]["job_id"], "slot": s, "power_mw": round(float(result.x[i]), 6), "energy_mwh": round(float(result.x[i] * SLOT_HOURS), 6)})
    total_energy = sum(item["energy_mwh"] for item in assignments)
    peak = max(float(intervals[s].get("baseline_mw", 0.0)) + sum(item["power_mw"] for item in assignments if item["slot"] == s) for s in slots)
    return SolverResult("optimal", float(-result.fun), assignments, {"scheduled_energy_mwh": round(total_energy, 6), "peak_mw": round(peak, 6), "jobs": len(jobs), "slots": len(slots)})
