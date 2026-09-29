#!/usr/bin/env python3
"""Audit and join the public Hack the Climate and EirGrid inputs.

The resulting CSV is intentionally a modelling contract, not a claim that
every dispatch-down event can be removed.  EirGrid's system curtailment and
local constraint labels remain separate throughout the join.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


HACK_FILES = {
    "generation": "IE_generation.csv",
    "load": "IE_load.csv",
    "price": "IE_SEM_prices.csv",
}


def _source_stats(frame: pd.DataFrame, timestamp: str) -> dict:
    ts = pd.to_datetime(frame[timestamp], errors="coerce")
    ordered = ts.dropna().sort_values()
    gaps = ordered.diff().dropna()
    return {
        "rows": int(len(frame)),
        "invalid_timestamps": int(ts.isna().sum()),
        "duplicate_timestamps": int(ts.duplicated().sum()),
        "min_timestamp": None if ordered.empty else ordered.iloc[0].isoformat(),
        "max_timestamp": None if ordered.empty else ordered.iloc[-1].isoformat(),
        "gap_counts": {str(k): int(v) for k, v in gaps.value_counts().head(10).items()},
    }


def _read_hack(raw_dir: Path) -> tuple[pd.DataFrame, dict]:
    generation = pd.read_csv(raw_dir / HACK_FILES["generation"])
    load = pd.read_csv(raw_dir / HACK_FILES["load"])
    price = pd.read_csv(raw_dir / HACK_FILES["price"])
    audit = {
        "generation": _source_stats(generation, "DateTime"),
        "load": _source_stats(load, "DateTime"),
        "price": _source_stats(price, "DateTime"),
        "generation_types": sorted(generation["ProductionType"].dropna().unique().tolist()),
    }

    generation["timestamp_utc"] = pd.to_datetime(generation["DateTime"], utc=True)
    generation["ActualGenerationOutput"] = pd.to_numeric(generation["ActualGenerationOutput"], errors="coerce")
    generation = generation[generation["ActualGenerationOutput"].notna()]
    wind = generation[generation["ProductionType"].eq("Wind Onshore")].groupby("timestamp_utc", as_index=False)["ActualGenerationOutput"].sum()
    wind = wind.rename(columns={"ActualGenerationOutput": "wind_actual_mw"})
    solar = generation[generation["ProductionType"].eq("Solar")].groupby("timestamp_utc", as_index=False)["ActualGenerationOutput"].sum()
    solar = solar.rename(columns={"ActualGenerationOutput": "solar_actual_mw"})

    load["timestamp_utc"] = pd.to_datetime(load["DateTime"], utc=True)
    load["TotalLoadValue"] = pd.to_numeric(load["TotalLoadValue"], errors="coerce")
    load = load[["timestamp_utc", "TotalLoadValue"]].dropna().drop_duplicates("timestamp_utc")
    load = load.rename(columns={"TotalLoadValue": "load_actual_mw"})

    price["timestamp_utc"] = pd.to_datetime(price["DateTime"], utc=True)
    price["Price[Currency/MWh]"] = pd.to_numeric(price["Price[Currency/MWh]"], errors="coerce")
    price = price[["timestamp_utc", "Price[Currency/MWh]"]].dropna().drop_duplicates("timestamp_utc").sort_values("timestamp_utc")
    price = price.rename(columns={"Price[Currency/MWh]": "price_eur_per_mwh"})

    base = pd.merge(wind, solar, on="timestamp_utc", how="outer")
    base = base.merge(load, on="timestamp_utc", how="outer")
    # The price feed is hourly.  Carry the latest published hourly value into
    # the following half-hour; no future price is introduced by this join.
    base = pd.merge_asof(base.sort_values("timestamp_utc"), price, on="timestamp_utc", direction="backward", tolerance=pd.Timedelta("1h"))
    for col in ["wind_actual_mw", "solar_actual_mw", "load_actual_mw"]:
        base[col] = pd.to_numeric(base[col], errors="coerce")
    return base.sort_values("timestamp_utc"), audit


def _read_labels(raw_dir: Path) -> tuple[pd.DataFrame, dict]:
    frames = []
    files = sorted((raw_dir / "eirgrid").glob("dd-hh-*.xlsx"))
    if not files:
        raise FileNotFoundError(f"No EirGrid DD-HH workbooks found under {raw_dir / 'eirgrid'}")
    for path in files:
        frame = pd.read_excel(path, sheet_name="DD HH")
        frame = frame[(frame["UT_TYPE"].eq("Wind")) & (frame["JURISDICTION"].eq("IE"))].copy()
        frame["timestamp_local"] = pd.to_datetime(frame["HH_TIMESTAMP"], errors="coerce")
        frame["gmt_offset_hours"] = pd.to_numeric(frame["GMT_OFFSET"], errors="coerce").fillna(0)
        # EirGrid publishes local half-hour timestamps plus the GMT offset.
        frame["timestamp_utc"] = (frame["timestamp_local"] - pd.to_timedelta(frame["gmt_offset_hours"], unit="h")).dt.tz_localize("UTC")
        frames.append(frame.assign(label_source=path.name))
    labels = pd.concat(frames, ignore_index=True)
    labels = labels.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")
    rename = {
        "Sum of CURTAILMENTS_MWH": "system_curtailment_mwh",
        "Sum of CONSTRAINTS_MWH": "local_constraint_mwh",
        "Sum of DD_MWH": "total_dispatch_down_mwh",
        "Sum of OTHER_MWH": "other_dispatch_down_mwh",
        "Sum of AV_MWH": "available_wind_mwh",
        "Sum of AO_MWH": "actual_output_wind_mwh",
    }
    labels = labels.rename(columns=rename)
    for col in rename.values():
        labels[col] = pd.to_numeric(labels[col], errors="coerce")
    keep = ["timestamp_utc", "timestamp_local", "gmt_offset_hours", *rename.values(), "label_source"]
    labels = labels[keep]
    audit = {
        "workbooks": [p.name for p in files],
        "rows_after_wind_ie_filter": int(len(labels)),
        "duplicate_timestamps_after_filter": int(sum(len(pd.read_excel(p, sheet_name="DD HH")) for p in files) - len(labels)),
        "min_timestamp_utc": labels["timestamp_utc"].min().isoformat(),
        "max_timestamp_utc": labels["timestamp_utc"].max().isoformat(),
        "curtailment_mwh": float(labels["system_curtailment_mwh"].sum()),
        "constraint_mwh": float(labels["local_constraint_mwh"].sum()),
        "dispatch_down_mwh": float(labels["total_dispatch_down_mwh"].sum()),
    }
    return labels, audit


def build(raw_dir: Path, processed_dir: Path) -> dict:
    hack, hack_audit = _read_hack(raw_dir / "hack_the_climate")
    labels, label_audit = _read_labels(raw_dir)
    joined = hack.merge(labels, on="timestamp_utc", how="left", suffixes=("", "_label"))
    joined["timestamp_local"] = joined["timestamp_utc"].dt.tz_convert("Europe/Dublin")
    joined["label_available"] = joined["total_dispatch_down_mwh"].notna()
    joined["load_forecast_mw"] = pd.NA
    joined["wind_forecast_mw"] = pd.NA
    joined["solar_forecast_mw"] = pd.NA
    joined["total_renewable_mw"] = joined["wind_actual_mw"].fillna(0) + joined["solar_actual_mw"].fillna(0)
    # Keep the public modelling contract first, followed by provenance fields.
    contract = [
        "timestamp_utc", "timestamp_local", "load_actual_mw", "load_forecast_mw",
        "wind_actual_mw", "wind_forecast_mw", "solar_actual_mw", "solar_forecast_mw",
        "total_renewable_mw",
        "price_eur_per_mwh", "system_curtailment_mwh", "local_constraint_mwh",
        "total_dispatch_down_mwh", "other_dispatch_down_mwh", "label_available",
        "label_source", "available_wind_mwh", "actual_output_wind_mwh", "gmt_offset_hours",
    ]
    for col in contract:
        if col not in joined:
            joined[col] = pd.NA
    result = joined[contract].sort_values("timestamp_utc").copy()
    result["timestamp_utc"] = result["timestamp_utc"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    result["timestamp_local"] = result["timestamp_local"].dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    processed_dir.mkdir(parents=True, exist_ok=True)
    csv_path = processed_dir / "turnup_30min.csv"
    result.to_csv(csv_path, index=False)
    labelled_csv_path = processed_dir / "turnup_labelled_30min.csv"
    result[result["label_available"] == True].to_csv(labelled_csv_path, index=False)  # noqa: E712

    labelled = result[result["label_available"] == True]  # noqa: E712
    report = {
        "team": "MilestoSmiles",
        "product": "TURNUP",
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "sources": {
            "hack_the_climate": "generation-load-prices.zip (IE_generation.csv, IE_load.csv, IE_SEM_prices.csv)",
            "eirgrid": "System and Renewable Data Reports / DD Half-Hourly Data; Wind + IE rows",
        },
        "hack_the_climate": hack_audit,
        "eirgrid": label_audit,
        "join": {
            "canonical_rows": int(len(result)),
            "labelled_rows": int(len(labelled)),
            "label_coverage_pct": round(float(len(labelled) / len(result) * 100), 2),
            "canonical_min_timestamp_utc": result["timestamp_utc"].min(),
            "canonical_max_timestamp_utc": result["timestamp_utc"].max(),
            "labelled_min_timestamp_utc": None if labelled.empty else labelled["timestamp_utc"].min(),
            "labelled_max_timestamp_utc": None if labelled.empty else labelled["timestamp_utc"].max(),
            "nulls": {k: int(v) for k, v in result.isna().sum().items() if int(v)},
        },
        "interpretation": {
            "system_curtailment_mwh": "EirGrid CURTAILMENTS_MWH; kept separate from local constraints.",
            "local_constraint_mwh": "EirGrid CONSTRAINTS_MWH; not treated as system curtailment.",
            "total_dispatch_down_mwh": "EirGrid DD_MWH; source total, not recomputed from the two components.",
            "forecast_leakage_guard": "Forecast columns are intentionally empty; actuals/labels are not presented as day-ahead features.",
        },
    }
    report_path = processed_dir / "audit_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return {"csv": csv_path, "labelled_csv": labelled_csv_path, "report": report_path, "report_data": report}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--processed-dir", type=Path, default=Path("data/processed"))
    args = parser.parse_args()
    output = build(args.raw_dir, args.processed_dir)
    join = output["report_data"]["join"]
    print(f"wrote {output['csv']} ({join['canonical_rows']} rows)")
    print(f"wrote {output['labelled_csv']} ({join['labelled_rows']} rows with EirGrid labels)")
    print(f"wrote {output['report']} ({join['labelled_rows']} labelled rows; {join['label_coverage_pct']}% coverage)")


if __name__ == "__main__":
    main()
