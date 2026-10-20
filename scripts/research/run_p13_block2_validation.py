from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    log_loss,
)

from run_p13_k2_model_feature_retest import (
    FEATURES_3,
    FEATURES_4,
    build_hgb,
    load_btc_context,
    load_development_rows,
    matrix,
)


ROOT = Path(__file__).resolve().parents[2]

CURRENT_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_prospective_supervised.csv"
)

OLD_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "pre_six_day_validation"
    / "p13_prospective_supervised_before_refresh.csv"
)

HGB4_MODEL_FILE = ROOT / "data" / "models" / "p13_hgb4_candidate_v1.joblib"

OUTPUT_REPORT = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_block2_validation_report.json"
)

OUTPUT_PREDICTIONS = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_block2_validation_predictions.csv"
)

BOOTSTRAP_SAMPLES = 10_000
RANDOM_SEED = 1337

GATED_HORIZONS = {
    120,
    60,
}


def metric_summary(
    y_true: np.ndarray,
    probability: np.ndarray,
) -> dict:
    probability = np.clip(
        probability,
        1e-12,
        1.0 - 1e-12,
    )

    prediction = (probability >= 0.5).astype(int)

    return {
        "rows": int(len(y_true)),
        "accuracy": float(
            accuracy_score(
                y_true,
                prediction,
            )
        ),
        "brier": float(
            brier_score_loss(
                y_true,
                probability,
            )
        ),
        "log_loss": float(
            log_loss(
                y_true,
                probability,
                labels=[
                    0,
                    1,
                ],
            )
        ),
    }


def market_cluster_bootstrap(
    frame: pd.DataFrame,
    model_column: str,
) -> dict:
    comparable = frame[frame["normalized_yes_mid"].notna()].copy()

    markets = sorted(comparable["condition_id"].unique())

    grouped = {
        market: group.copy() for market, group in comparable.groupby("condition_id")
    }

    rng = np.random.default_rng(RANDOM_SEED)

    brier_deltas = np.empty(
        BOOTSTRAP_SAMPLES,
        dtype=float,
    )

    logloss_deltas = np.empty(
        BOOTSTRAP_SAMPLES,
        dtype=float,
    )

    for i in range(BOOTSTRAP_SAMPLES):
        sampled_markets = rng.choice(
            markets,
            size=len(markets),
            replace=True,
        )

        sampled_groups = [grouped[market] for market in sampled_markets]

        sample = pd.concat(
            sampled_groups,
            ignore_index=True,
        )

        y = sample["label_yes"].to_numpy(dtype=int)

        model_p = sample[model_column].to_numpy(dtype=float)

        market_p = sample["normalized_yes_mid"].to_numpy(dtype=float)

        brier_deltas[i] = brier_score_loss(
            y,
            model_p,
        ) - brier_score_loss(
            y,
            market_p,
        )

        logloss_deltas[i] = log_loss(
            y,
            model_p,
            labels=[
                0,
                1,
            ],
        ) - log_loss(
            y,
            market_p,
            labels=[
                0,
                1,
            ],
        )

    def summarize_delta(
        values: np.ndarray,
    ) -> dict:
        return {
            "mean": float(np.mean(values)),
            "ci95_low": float(
                np.quantile(
                    values,
                    0.025,
                )
            ),
            "ci95_high": float(
                np.quantile(
                    values,
                    0.975,
                )
            ),
            "probability_model_better": float(np.mean(values < 0.0)),
        }

    return {
        "markets": int(len(markets)),
        "rows": int(len(comparable)),
        "bootstrap_samples": (BOOTSTRAP_SAMPLES),
        "brier_model_minus_market": (summarize_delta(brier_deltas)),
        "log_loss_model_minus_market": (summarize_delta(logloss_deltas)),
    }


def load_fresh_block() -> tuple[
    pd.DataFrame,
    dict,
]:
    current = pd.read_csv(CURRENT_FILE)

    old = pd.read_csv(OLD_FILE)

    current["condition_id"] = (
        current["condition_id"].astype(str).str.strip().str.lower()
    )

    old["condition_id"] = old["condition_id"].astype(str).str.strip().str.lower()

    current["prediction_timestamp_dt"] = pd.to_datetime(
        current["prediction_timestamp"],
        utc=True,
    )

    current["market_end_at_dt"] = pd.to_datetime(
        current["market_end_at"],
        utc=True,
    )

    old["market_end_at_dt"] = pd.to_datetime(
        old["market_end_at"],
        utc=True,
    )

    old_markets = set(old["condition_id"].unique())

    old_last_market_end = old["market_end_at_dt"].max()

    fresh = current[
        ~current["condition_id"].isin(old_markets)
        & (current["market_end_at_dt"] > old_last_market_end)
    ].copy()

    fresh_market_overlap = len(set(fresh["condition_id"].unique()) & old_markets)

    complete_mask = (
        fresh["snapshot_complete"].astype(bool)
        & fresh["reference_return_30s_complete"].astype(bool)
        & fresh["rtds_context_complete"].astype(bool)
        & fresh["label_yes"].notna()
        & fresh["relative_distance_from_strike"].notna()
        & fresh["reference_return_30s"].notna()
        & fresh["rtds_ohlc_return_1m"].notna()
    )

    complete = fresh[complete_mask].copy()

    complete = complete.sort_values(
        [
            "prediction_timestamp_dt",
            "condition_id",
            "target_horizon_seconds",
        ]
    ).reset_index(drop=True)

    info = {
        "old_rows": int(len(old)),
        "old_markets": int(old["condition_id"].nunique()),
        "old_last_market_end": (old_last_market_end.isoformat()),
        "fresh_all_rows": int(len(fresh)),
        "fresh_all_markets": int(fresh["condition_id"].nunique()),
        "fresh_complete_rows": int(len(complete)),
        "fresh_complete_markets": int(complete["condition_id"].nunique()),
        "market_overlap_with_old": int(fresh_market_overlap),
        "first_fresh_prediction": (
            complete["prediction_timestamp_dt"].min().isoformat()
        ),
        "last_fresh_prediction": (
            complete["prediction_timestamp_dt"].max().isoformat()
        ),
    }

    return (
        complete,
        info,
    )


def build_historical_hgb3():
    btc_context = load_btc_context()

    development_rows = load_development_rows(btc_context)

    x3, y = matrix(
        development_rows,
        FEATURES_3,
    )

    model = build_hgb()

    model.fit(
        x3,
        y,
    )

    historical_rtds_like = np.array(
        [float(row["btc_return_1m"]) for row in development_rows],
        dtype=float,
    )

    return (
        model,
        development_rows,
        historical_rtds_like,
    )


def main() -> None:
    if not CURRENT_FILE.exists():
        raise FileNotFoundError(CURRENT_FILE)

    if not OLD_FILE.exists():
        raise FileNotFoundError(OLD_FILE)

    if not HGB4_MODEL_FILE.exists():
        raise FileNotFoundError(f"Frozen HGB4 candidate missing: {HGB4_MODEL_FILE}")

    fresh, block_info = load_fresh_block()

    if block_info["market_overlap_with_old"] != 0:
        raise RuntimeError("Fresh block overlaps old markets.")

    print("FRESH PROSPECTIVE BLOCK")

    for key, value in block_info.items():
        print(f"{key}={value}")

    print()

    if len(fresh) == 0:
        raise RuntimeError("No complete fresh rows.")

    hgb3, development_rows, historical_return = build_historical_hgb3()

    hgb4 = joblib.load(HGB4_MODEL_FILE)

    x3 = fresh[list(FEATURES_3)].to_numpy(dtype=float)

    x4 = fresh[
        [
            "relative_distance_from_strike",
            "target_horizon_seconds",
            "reference_return_30s",
            "rtds_ohlc_return_1m",
        ]
    ].to_numpy(dtype=float)

    y = fresh["label_yes"].to_numpy(dtype=int)

    hgb3_probability = hgb3.predict_proba(x3)[
        :,
        1,
    ]

    hgb4_probability = hgb4.predict_proba(x4)[
        :,
        1,
    ]

    horizons = fresh["target_horizon_seconds"].to_numpy(dtype=int)

    gated_probability = np.where(
        np.isin(
            horizons,
            list(GATED_HORIZONS),
        ),
        hgb4_probability,
        hgb3_probability,
    )

    fresh["hgb3_probability"] = hgb3_probability

    fresh["hgb4_rtds_probability"] = hgb4_probability

    fresh["gated_probability"] = gated_probability

    overall = {
        "HGB3": metric_summary(
            y,
            hgb3_probability,
        ),
        "HGB4_RTDS": metric_summary(
            y,
            hgb4_probability,
        ),
        "GATED": metric_summary(
            y,
            gated_probability,
        ),
    }

    overall["HGB4_RTDS_minus_HGB3"] = {
        "brier": (overall["HGB4_RTDS"]["brier"] - overall["HGB3"]["brier"]),
        "log_loss": (overall["HGB4_RTDS"]["log_loss"] - overall["HGB3"]["log_loss"]),
        "accuracy": (overall["HGB4_RTDS"]["accuracy"] - overall["HGB3"]["accuracy"]),
    }

    overall["GATED_minus_HGB3"] = {
        "brier": (overall["GATED"]["brier"] - overall["HGB3"]["brier"]),
        "log_loss": (overall["GATED"]["log_loss"] - overall["HGB3"]["log_loss"]),
        "accuracy": (overall["GATED"]["accuracy"] - overall["HGB3"]["accuracy"]),
    }

    by_horizon = {}

    for horizon in sorted(
        fresh["target_horizon_seconds"].unique(),
        reverse=True,
    ):
        subset = fresh[fresh["target_horizon_seconds"] == horizon]

        subset_y = subset["label_yes"].to_numpy(dtype=int)

        by_horizon[str(int(horizon))] = {
            "HGB3": metric_summary(
                subset_y,
                subset["hgb3_probability"].to_numpy(dtype=float),
            ),
            "HGB4_RTDS": metric_summary(
                subset_y,
                subset["hgb4_rtds_probability"].to_numpy(dtype=float),
            ),
            "GATED": metric_summary(
                subset_y,
                subset["gated_probability"].to_numpy(dtype=float),
            ),
        }

        by_horizon[str(int(horizon))]["HGB4_minus_HGB3_brier"] = (
            by_horizon[str(int(horizon))]["HGB4_RTDS"]["brier"]
            - by_horizon[str(int(horizon))]["HGB3"]["brier"]
        )

    historical_return = historical_return[np.isfinite(historical_return)]

    prospective_return = fresh["rtds_ohlc_return_1m"].to_numpy(dtype=float)

    distribution = {
        "historical_bitstamp": {
            "count": int(len(historical_return)),
            "mean": float(np.mean(historical_return)),
            "std": float(
                np.std(
                    historical_return,
                    ddof=1,
                )
            ),
        },
        "fresh_rtds": {
            "count": int(len(prospective_return)),
            "mean": float(np.mean(prospective_return)),
            "std": float(
                np.std(
                    prospective_return,
                    ddof=1,
                )
            ),
        },
    }

    historical_std = distribution["historical_bitstamp"]["std"]

    fresh_std = distribution["fresh_rtds"]["std"]

    distribution["fresh_to_historical_std_ratio"] = fresh_std / historical_std

    market_comparison = {}

    for model_name, column in (
        (
            "HGB3",
            "hgb3_probability",
        ),
        (
            "HGB4_RTDS",
            "hgb4_rtds_probability",
        ),
        (
            "GATED",
            "gated_probability",
        ),
    ):
        common = fresh[fresh["normalized_yes_mid"].notna()]

        common_y = common["label_yes"].to_numpy(dtype=int)

        model_metrics = metric_summary(
            common_y,
            common[column].to_numpy(dtype=float),
        )

        market_metrics = metric_summary(
            common_y,
            common["normalized_yes_mid"].to_numpy(dtype=float),
        )

        market_comparison[model_name] = {
            "common_rows": int(len(common)),
            "common_markets": int(common["condition_id"].nunique()),
            "model": model_metrics,
            "market": market_metrics,
            "brier_model_minus_market": (
                model_metrics["brier"] - market_metrics["brier"]
            ),
            "log_loss_model_minus_market": (
                model_metrics["log_loss"] - market_metrics["log_loss"]
            ),
            "bootstrap": (
                market_cluster_bootstrap(
                    fresh,
                    column,
                )
            ),
        }

    report = {
        "experiment": ("p13_block2_validation"),
        "prospective_block": (block_info),
        "gated_horizons": sorted(
            GATED_HORIZONS,
            reverse=True,
        ),
        "historical_training_rows": int(len(development_rows)),
        "historical_training_markets": int(
            len({row["condition_id"] for row in development_rows})
        ),
        "overall": overall,
        "by_horizon": by_horizon,
        "feature_distribution": (distribution),
        "market_comparison": (market_comparison),
        "interpretation_rules": {
            "negative_HGB4_minus_HGB3": ("RTDS-substituted HGB4 improves over HGB3."),
            "negative_GATED_minus_HGB3": (
                "The pre-specified 120s/60s horizon gating improves over HGB3."
            ),
            "negative_model_minus_market": (
                "The model beats Polymarket on the relevant proper score."
            ),
        },
    }

    OUTPUT_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    output_columns = [
        "condition_id",
        "target_horizon_seconds",
        "prediction_timestamp",
        "market_end_at",
        "relative_distance_from_strike",
        "reference_return_30s",
        "rtds_ohlc_return_1m",
        "normalized_yes_mid",
        "label_yes",
        "hgb3_probability",
        "hgb4_rtds_probability",
        "gated_probability",
    ]

    fresh[output_columns].to_csv(
        OUTPUT_PREDICTIONS,
        index=False,
    )

    print("P13 BLOCK 2 VALIDATION COMPLETE")

    print()

    print(
        "fresh_complete_rows=",
        len(fresh),
    )

    print(
        "fresh_complete_markets=",
        fresh["condition_id"].nunique(),
    )

    print(
        "market_overlap_with_old=",
        block_info["market_overlap_with_old"],
    )

    print()

    print("OVERALL")

    for name, metrics in overall.items():
        print(
            name,
            metrics,
        )

    print()

    print("BY HORIZON")

    for horizon, metrics in by_horizon.items():
        print()
        print(
            "horizon",
            horizon,
        )

        for name, value in metrics.items():
            print(
                name,
                value,
            )

    print()

    print("FEATURE DISTRIBUTION")

    print(distribution)

    print()

    print("MARKET COMPARISON")

    for name, value in market_comparison.items():
        print()
        print(
            name,
            value,
        )

    print()

    print(
        "report=",
        OUTPUT_REPORT,
    )

    print(
        "predictions=",
        OUTPUT_PREDICTIONS,
    )


if __name__ == "__main__":
    main()
