#!/usr/bin/env python3
"""Compare fixed, price-only, TURNUP and oracle schedules on held-out days."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd


SLOT_HOURS = 0.5


def slot_number(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 2 + int(minute) // 30


def load_jobs(path: Path) -> list[dict]:
    jobs = pd.read_csv(path).to_dict("records")
    for job in jobs:
        job["earliest"] = slot_number(job.pop("earliest_start_local"))
        job["deadline"] = slot_number(job.pop("deadline_local"))
        job["energy_mwh"] = float(job["energy_mwh"])
        job["max_power_mw"] = float(job["max_power_mw"])
    return jobs


def load_baseline(path: Path) -> pd.DataFrame:
    baseline = pd.read_csv(path)
    baseline["slot"] = baseline["interval_local"].map(slot_number)
    return baseline.sort_values("slot").set_index("slot")


def choose_score(strategy: str, frame: pd.DataFrame) -> pd.Series:
    if strategy == "fixed":
        # Fixed means earliest feasible execution, independent of signals.
        return -frame["slot"]
    if strategy == "price_only":
        return -frame["price_eur_per_mwh"].fillna(frame["price_eur_per_mwh"].median())
    if strategy == "turnup":
        return frame["model_expected_curtailment_mwh"].clip(lower=0)
    if strategy == "oracle":
        return frame["system_curtailment_mwh"].clip(lower=0)
    raise ValueError(strategy)


def schedule_day(day: pd.DataFrame, jobs: list[dict], baseline: pd.DataFrame, strategy: str, peak_cap: float | None = None) -> tuple[pd.DataFrame, dict]:
    slots = pd.DataFrame({"slot": range(48)})
    slots = slots.merge(day[["slot", "price_eur_per_mwh", "system_curtailment_mwh", "model_expected_curtailment_mwh"]], on="slot", how="left")
    slots["price_eur_per_mwh"] = slots["price_eur_per_mwh"].ffill().bfill().fillna(0)
    slots["system_curtailment_mwh"] = slots["system_curtailment_mwh"].fillna(0)
    slots["model_expected_curtailment_mwh"] = slots["model_expected_curtailment_mwh"].fillna(0)
    slots["baseline_mw"] = slots["slot"].map(baseline["site_baseline_mw"])
    slots["scheduled_mw"] = 0.0
    assignments: list[dict] = []
    unmet_total = 0.0
    deadline_misses = 0
    capacity_violations = 0
    ordered_jobs = sorted(jobs, key=lambda j: (j["deadline"], j["priority"]))
    for job in ordered_jobs:
        remaining = job["energy_mwh"]
        candidates = slots[(slots.slot >= job["earliest"]) & (slots.slot < job["deadline"])].copy()
        candidates["score"] = choose_score(strategy, candidates)
        if strategy == "fixed":
            candidates = candidates.sort_values("slot")
        else:
            candidates = candidates.sort_values(["score", "slot"], ascending=[False, True])
        if job["job_type"].lower() == "continuous":
            needed = math.ceil(remaining / (job["max_power_mw"] * SLOT_HOURS) - 1e-9)
            starts = []
            candidate_slots = set(candidates.slot.tolist())
            for start in range(job["earliest"], job["deadline"] - needed + 1):
                if all(s in candidate_slots for s in range(start, start + needed)):
                    starts.append(start)
            selected_slots = set(range(starts[0], starts[0] + needed)) if starts else set()
            selected = slots[slots.slot.isin(selected_slots)]
        else:
            selected = candidates
        for idx in selected.index:
            if remaining <= 1e-6:
                break
            capacity = baseline.loc[int(slots.at[idx, "slot"]), "site_import_capacity_mw"] - slots.at[idx, "baseline_mw"] - slots.at[idx, "scheduled_mw"]
            if peak_cap is not None:
                capacity = min(capacity, peak_cap - slots.at[idx, "baseline_mw"] - slots.at[idx, "scheduled_mw"])
            power = min(job["max_power_mw"], max(0.0, capacity), remaining / SLOT_HOURS)
            if power <= 1e-8:
                continue
            slots.at[idx, "scheduled_mw"] += power
            energy = power * SLOT_HOURS
            remaining -= energy
            assignments.append({"job_id": job["job_id"], "slot": int(slots.at[idx, "slot"]), "power_mw": power, "energy_mwh": energy})
        if remaining > 1e-5:
            unmet_total += remaining
            deadline_misses += 1
    slots["total_mw"] = slots["baseline_mw"] + slots["scheduled_mw"]
    capacity_violations = int((slots["total_mw"] > baseline["site_import_capacity_mw"].to_numpy() + 1e-6).sum())
    if peak_cap is not None:
        capacity_violations += int((slots["total_mw"] > peak_cap + 1e-6).sum())
    fixed_power = None
    stats = {
        "strategy": strategy,
        "scheduled_energy_mwh": float(slots["scheduled_mw"].sum() * SLOT_HOURS),
        "unmet_energy_mwh": float(unmet_total),
        "deadline_misses": deadline_misses,
        "capacity_violations": capacity_violations,
        "peak_mw": float(slots["total_mw"].max()),
        "curtailment_overlap_mwh": float((slots["scheduled_mw"] * SLOT_HOURS).clip(upper=slots["system_curtailment_mwh"]).sum()),
        "energy_cost_eur": float((slots["scheduled_mw"] * SLOT_HOURS * slots["price_eur_per_mwh"]).sum()),
        "assignments": assignments,
    }
    return slots, stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, default=Path("data/processed/predictions_test.csv"))
    parser.add_argument("--labels", type=Path, default=Path("data/processed/turnup_labelled_30min.csv"))
    parser.add_argument("--workloads", type=Path, default=Path("data/workloads.csv"))
    parser.add_argument("--baseline", type=Path, default=Path("data/site_baseline.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/processed"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    predictions = pd.read_csv(args.predictions, parse_dates=["timestamp_utc"])
    labels = pd.read_csv(args.labels, usecols=["timestamp_utc", "price_eur_per_mwh"], parse_dates=["timestamp_utc"])
    data = predictions.merge(labels, on="timestamp_utc", how="left")
    data["date"] = data["timestamp_utc"].dt.date
    data["slot"] = data["timestamp_utc"].dt.hour * 2 + data["timestamp_utc"].dt.minute // 30
    jobs = load_jobs(args.workloads)
    baseline = load_baseline(args.baseline)
    full_days = [day for day, group in data.groupby("date") if len(group) == 48 and set(group.slot) == set(range(48))]
    if not full_days:
        raise RuntimeError("No complete 48-slot test days available")
    fixed_peaks = []
    for date in full_days:
        _, stats = schedule_day(data[data.date == date], jobs, baseline, "fixed")
        fixed_peaks.append(stats["peak_mw"])
    fixed_peak_cap = max(fixed_peaks)
    daily_rows: list[dict] = []
    assignment_rows: list[dict] = []
    for date in full_days:
        day = data[data.date == date].copy()
        fixed_slots, fixed_stats = schedule_day(day, jobs, baseline, "fixed")
        for strategy in ["fixed", "price_only", "turnup", "oracle"]:
            if strategy == "fixed":
                slots, stats = fixed_slots, fixed_stats
            else:
                slots, stats = schedule_day(day, jobs, baseline, strategy, peak_cap=fixed_peak_cap)
            strategy_assignments = stats["assignments"]
            stats = {k: v for k, v in stats.items() if k != "assignments"}
            stats["date"] = str(date)
            stats["strategy"] = strategy
            stats["schedule_movement_mwh"] = 0.0 if strategy == "fixed" else float((slots["scheduled_mw"] - fixed_slots["scheduled_mw"]).abs().sum() * SLOT_HOURS / 2)
            daily_rows.append(stats)
            for assignment in strategy_assignments:
                assignment_rows.append({"date": str(date), "strategy": strategy, **assignment})
    daily = pd.DataFrame(daily_rows)
    assignments = pd.DataFrame(assignment_rows)
    daily.to_csv(args.output / "schedule_daily_comparison.csv", index=False)
    assignments.to_csv(args.output / "schedule_assignments.csv", index=False)
    summary = {}
    for strategy, group in daily.groupby("strategy"):
        fixed_overlap = float(daily[daily.strategy == "fixed"]["curtailment_overlap_mwh"].mean())
        summary[strategy] = {
            "days": int(len(group)),
            "mean_curtailment_overlap_mwh": round(float(group.curtailment_overlap_mwh.mean()), 5),
            "total_curtailment_overlap_mwh": round(float(group.curtailment_overlap_mwh.sum()), 5),
            "incremental_overlap_vs_fixed_mwh": round(float(group.curtailment_overlap_mwh.sum() - daily[daily.strategy == "fixed"].curtailment_overlap_mwh.sum()), 5),
            "mean_energy_cost_eur": round(float(group.energy_cost_eur.mean()), 5),
            "mean_peak_mw": round(float(group.peak_mw.mean()), 5),
            "max_peak_mw": round(float(group.peak_mw.max()), 5),
            "total_scheduled_energy_mwh": round(float(group.scheduled_energy_mwh.sum()), 5),
            "total_unmet_energy_mwh": round(float(group.unmet_energy_mwh.sum()), 5),
            "deadline_misses": int(group.deadline_misses.sum()),
            "capacity_violations": int(group.capacity_violations.sum()),
            "mean_schedule_movement_mwh": round(float(group.schedule_movement_mwh.mean()), 5),
        }
    energy_targets = {round(float(values["total_scheduled_energy_mwh"]), 6) for values in summary.values()}
    if len(energy_targets) != 1:
        raise RuntimeError(f"Strategies changed the workload energy target: {energy_targets}")
    bad = {strategy: (values["deadline_misses"], values["capacity_violations"]) for strategy, values in summary.items() if values["deadline_misses"] or values["capacity_violations"]}
    if bad:
        raise RuntimeError(f"Schedule guardrail violations: {bad}")
    report = {
        "evaluation": "Held-out complete 48-slot historical days; actual system curtailment is used only by the oracle and for scoring.",
        "days_evaluated": len(full_days),
        "days_excluded_incomplete": int(data.date.nunique() - len(full_days)),
        "fixed_peak_cap_mw": fixed_peak_cap,
        "strategies": summary,
        "guardrails": {"all_schedules_same_energy_target": True, "deadline_misses_must_be_zero": True, "capacity_violations_must_be_zero": True},
    }
    (args.output / "schedule_metrics.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"days={len(full_days)} excluded_incomplete={report['days_excluded_incomplete']} fixed_peak_cap_mw={fixed_peak_cap:.2f}")
    for strategy, values in summary.items():
        print(f"{strategy}: overlap={values['total_curtailment_overlap_mwh']:.2f} MWh cost={values['mean_energy_cost_eur']:.2f} peak={values['max_peak_mw']:.2f} MW deadline_misses={values['deadline_misses']}")
    print(f"wrote {args.output / 'schedule_metrics.json'}")


if __name__ == "__main__":
    main()
