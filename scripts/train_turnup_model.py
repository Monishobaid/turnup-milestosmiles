#!/usr/bin/env python3
"""Train the first leakage-safe TURNUP baseline and write test artifacts.

The public Hack the Climate extract contains actual measurements rather than
published day-ahead forecasts.  Consequently this script uses past-only lag
and rolling features and reports a historical, short-horizon simulation.  It
does not present same-interval actuals as a deployable day-ahead forecast.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    mean_absolute_error,
    precision_score,
    recall_score,
)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


LAGS = {"1h": 2, "3h": 6, "6h": 12, "24h": 48, "48h": 96, "7d": 336}
BASE_SIGNALS = ["wind_actual_mw", "load_actual_mw", "price_eur_per_mwh", "total_renewable_mw", "residual_load_mw"]


def _bounded_low(series: pd.Series, low: float, high: float) -> pd.Series:
    return (1 - ((series - low) / max(high - low, 1e-9))).clip(0, 1)


def make_features(path: Path) -> tuple[pd.DataFrame, list[str], dict]:
    raw = pd.read_csv(path, parse_dates=["timestamp_utc"])
    raw = raw[raw["label_available"].astype(str).str.lower().eq("true")].copy()
    raw = raw.sort_values("timestamp_utc").drop_duplicates("timestamp_utc")
    raw = raw.set_index("timestamp_utc")
    raw = raw[~raw.index.duplicated(keep="last")]
    full_index = pd.date_range(raw.index.min(), raw.index.max(), freq="30min", tz="UTC")
    frame = raw.reindex(full_index)
    frame.index.name = "timestamp_utc"
    frame["system_curtailment_mwh"] = pd.to_numeric(frame["system_curtailment_mwh"], errors="coerce")
    frame["load_actual_mw"] = pd.to_numeric(frame["load_actual_mw"], errors="coerce").ffill()
    frame["wind_actual_mw"] = pd.to_numeric(frame["wind_actual_mw"], errors="coerce").ffill()
    frame["solar_actual_mw"] = pd.to_numeric(frame["solar_actual_mw"], errors="coerce").fillna(0)
    frame["price_eur_per_mwh"] = pd.to_numeric(frame["price_eur_per_mwh"], errors="coerce").ffill()
    frame["total_renewable_mw"] = frame["wind_actual_mw"].fillna(0) + frame["solar_actual_mw"].fillna(0)
    frame["residual_load_mw"] = frame["load_actual_mw"] - frame["total_renewable_mw"]

    # All model features below are lagged or calendar features.  No current
    # interval actual or target is supplied to either model.
    features: list[str] = []
    for signal in BASE_SIGNALS:
        for name, periods in LAGS.items():
            col = f"{signal}_lag_{name}"
            frame[col] = frame[signal].shift(periods)
            features.append(col)
    hours = frame.index.hour + frame.index.minute / 60
    frame["hour_sin"] = np.sin(2 * np.pi * hours / 24)
    frame["hour_cos"] = np.cos(2 * np.pi * hours / 24)
    frame["dow_sin"] = np.sin(2 * np.pi * frame.index.dayofweek / 7)
    frame["dow_cos"] = np.cos(2 * np.pi * frame.index.dayofweek / 7)
    frame["month"] = frame.index.month
    frame["is_weekend"] = (frame.index.dayofweek >= 5).astype(int)
    features += ["hour_sin", "hour_cos", "dow_sin", "dow_cos", "month", "is_weekend"]
    frame["event"] = (frame["system_curtailment_mwh"] > 0.01).astype(float)

    valid = frame[features + ["system_curtailment_mwh", "event"]].notna().all(axis=1)
    frame = frame.loc[valid].copy()
    frame["timestamp_utc"] = frame.index
    # Past-only historical event tendency used by the transparent heuristic.
    frame["historical_event_rate_7d"] = frame["event"].shift(1).rolling(336, min_periods=48).mean()
    frame = frame.dropna(subset=["historical_event_rate_7d"])
    feature_metadata = {
        "feature_count": len(features),
        "features": features,
        "lags": LAGS,
        "target_threshold_mwh": 0.01,
        "feature_safety": "Only past lags, past rolling event rate and calendar variables are used; no current actuals or labels.",
        "rows_after_time_safe_features": int(len(frame)),
        "min_timestamp_utc": frame["timestamp_utc"].min().isoformat(),
        "max_timestamp_utc": frame["timestamp_utc"].max().isoformat(),
    }
    return frame, features, feature_metadata


def split_time(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    n = len(frame)
    train_end = int(n * 0.65)
    valid_end = int(n * 0.80)
    return frame.iloc[:train_end], frame.iloc[train_end:valid_end], frame.iloc[valid_end:]


def top_decile_recall(y_true: np.ndarray, score: np.ndarray) -> float:
    count = max(1, int(np.ceil(len(score) * 0.10)))
    top = np.argsort(score)[-count:]
    positives = max(1, int(y_true.sum()))
    return float(y_true[top].sum() / positives)


def calibration_rows(y_true: np.ndarray, score: np.ndarray) -> list[dict]:
    actual, predicted = calibration_curve(y_true, score, n_bins=10, strategy="quantile")
    return [{"mean_predicted": round(float(p), 5), "event_rate": round(float(a), 5)} for a, p in zip(actual, predicted)]


def evaluate(y_true: np.ndarray, probability: np.ndarray, magnitude: np.ndarray, heuristic: np.ndarray, actual_mwh: np.ndarray) -> dict:
    thresholded = probability >= 0.5
    return {
        "rows": int(len(y_true)),
        "event_count": int(y_true.sum()),
        "event_rate": round(float(y_true.mean()), 5),
        "model": {
            "pr_auc": round(float(average_precision_score(y_true, probability)), 5),
            "precision_at_0_5": round(float(precision_score(y_true, thresholded, zero_division=0)), 5),
            "recall_at_0_5": round(float(recall_score(y_true, thresholded, zero_division=0)), 5),
            "top_decile_recall": round(top_decile_recall(y_true, probability), 5),
            "top_decile_lift": round(float((y_true[np.argsort(probability)[-max(1, int(np.ceil(len(y_true) * .1))):]].mean()) / max(y_true.mean(), 1e-9)), 5),
            "brier": round(float(brier_score_loss(y_true, probability)), 5),
            "magnitude_mae_mwh": round(float(mean_absolute_error(actual_mwh, magnitude)), 5),
            "calibration": calibration_rows(y_true, probability),
        },
        "heuristic": {
            "pr_auc": round(float(average_precision_score(y_true, heuristic)), 5),
            "top_decile_recall": round(top_decile_recall(y_true, heuristic), 5),
            "top_decile_lift": round(float((y_true[np.argsort(heuristic)[-max(1, int(np.ceil(len(y_true) * .1))):]].mean()) / max(y_true.mean(), 1e-9)), 5),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/processed/turnup_labelled_30min.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/processed"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    frame, features, metadata = make_features(args.data)
    train, valid, test = split_time(frame)
    train_valid = pd.concat([train, valid])
    x_train = train[features]
    x_train_valid = train_valid[features]
    x_test = test[features]
    y_train = train["event"].astype(int).to_numpy()
    y_train_valid = train_valid["event"].astype(int).to_numpy()
    y_test = test["event"].astype(int).to_numpy()

    event_model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42))
    event_model.fit(x_train_valid, y_train_valid)
    test_probability = event_model.predict_proba(x_test)[:, 1]

    positive = train_valid[train_valid["event"] == 1]
    magnitude_model = HistGradientBoostingRegressor(max_iter=180, learning_rate=0.06, max_leaf_nodes=15, l2_regularization=1.0, random_state=42)
    magnitude_model.fit(positive[features], positive["system_curtailment_mwh"])
    conditional = np.maximum(0, magnitude_model.predict(x_test))
    expected_magnitude = test_probability * conditional

    # Transparent historical surplus score. Bounds are fitted on train+valid;
    # its current-interval inputs are explicitly not treated as a forecast.
    fit = train_valid
    renewable_share = (fit["total_renewable_mw"] / fit["load_actual_mw"].clip(lower=1)).replace([np.inf, -np.inf], np.nan)
    test_share = (test["total_renewable_mw"] / test["load_actual_mw"].clip(lower=1)).replace([np.inf, -np.inf], np.nan)
    share_low, share_high = renewable_share.quantile([.05, .95])
    residual_low, residual_high = fit["residual_load_mw"].quantile([.05, .95])
    price_low, price_high = fit["price_eur_per_mwh_lag_1h"].quantile([.05, .95])
    heuristic = (
        0.35 * ((test_share - share_low) / max(share_high - share_low, 1e-9)).clip(0, 1)
        + 0.30 * _bounded_low(test["residual_load_mw"], residual_low, residual_high)
        + 0.20 * _bounded_low(test["price_eur_per_mwh_lag_1h"], price_low, price_high)
        + 0.15 * test["historical_event_rate_7d"].clip(0, 1)
    ).fillna(0).to_numpy()
    actual = test["system_curtailment_mwh"].to_numpy()
    metrics = evaluate(y_test, test_probability, expected_magnitude, heuristic, actual)
    metadata.update({
        "split": {"train_rows": len(train), "validation_rows": len(valid), "test_rows": len(test), "train_end": train.timestamp_utc.max().isoformat(), "validation_end": valid.timestamp_utc.max().isoformat(), "test_end": test.timestamp_utc.max().isoformat()},
        "model": "LogisticRegression event probability + HistGradientBoostingRegressor conditional magnitude",
        "historical_heuristic": "renewable share + low residual load + low lagged price + past 7-day event rate; historical simulation only",
    })
    (args.output / "feature_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (args.output / "model_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    predictions = test[["timestamp_utc", "system_curtailment_mwh", "event"]].copy()
    predictions["model_event_probability"] = test_probability
    predictions["model_expected_curtailment_mwh"] = expected_magnitude
    predictions["heuristic_opportunity_score"] = heuristic
    predictions.to_csv(args.output / "predictions_test.csv", index=False)
    model_dir = args.output / "models"
    model_dir.mkdir(exist_ok=True)
    joblib.dump(event_model, model_dir / "event_model.joblib")
    joblib.dump(magnitude_model, model_dir / "magnitude_model.joblib")
    print(f"rows={len(frame)} train={len(train)} validation={len(valid)} test={len(test)}")
    print(f"model_pr_auc={metrics['model']['pr_auc']} heuristic_pr_auc={metrics['heuristic']['pr_auc']}")
    print(f"model_top_decile_recall={metrics['model']['top_decile_recall']} heuristic_top_decile_recall={metrics['heuristic']['top_decile_recall']}")
    print(f"wrote {args.output / 'model_metrics.json'} and {args.output / 'predictions_test.csv'}")


if __name__ == "__main__":
    main()
