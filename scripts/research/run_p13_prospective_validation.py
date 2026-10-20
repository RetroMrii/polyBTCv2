from __future__ import annotations

import csv
import json

from pathlib import Path

import numpy as np

from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    log_loss,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[2]

HISTORICAL_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_enriched_supervised.csv"
)

PROSPECTIVE_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_prospective_supervised.csv"
)

OUTPUT_REPORT = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_prospective_validation_report.json"
)

OUTPUT_PREDICTIONS = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_prospective_validation_predictions.csv"
)


REPORT_VERSION = "p13_prospective_validation_v1"


BASELINE_FEATURES = (
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
)


HISTORICAL_MODEL_B_FEATURES = (
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
    "btc_return_1m",
)


PROSPECTIVE_MODEL_B_FEATURES = (
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
    "rtds_ohlc_return_1m",
)


HORIZONS = (
    240,
    180,
    120,
    90,
    60,
    30,
)


def optional_float(
    value: object,
) -> float | None:
    if value is None:
        return None

    raw = str(value).strip()

    if not raw:
        return None

    return float(raw)


def build_model() -> Pipeline:
    return Pipeline(
        [
            (
                "scaler",
                StandardScaler(),
            ),
            (
                "logistic",
                LogisticRegression(
                    max_iter=1000,
                    solver="lbfgs",
                ),
            ),
        ]
    )


def calculate_metrics(
    y: np.ndarray,
    probabilities: np.ndarray,
) -> dict:
    predicted = (probabilities >= 0.5).astype(int)

    return {
        "rows": int(len(y)),
        "accuracy": float(
            accuracy_score(
                y,
                predicted,
            )
        ),
        "brier": float(
            brier_score_loss(
                y,
                probabilities,
            )
        ),
        "log_loss": float(
            log_loss(
                y,
                probabilities,
                labels=[
                    0,
                    1,
                ],
            )
        ),
        "positive_rate": float(np.mean(y)),
        "mean_probability": float(np.mean(probabilities)),
    }


def load_historical() -> list[dict]:
    rows = []

    required = set(BASELINE_FEATURES) | {
        "btc_return_1m",
    }

    with HISTORICAL_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            label_raw = row.get(
                "label_yes",
                "",
            ).strip()

            if label_raw not in {
                "0",
                "1",
            }:
                continue

            values = {feature: optional_float(row.get(feature)) for feature in required}

            if any(value is None for value in values.values()):
                continue

            rows.append(
                {
                    "condition_id": (row["condition_id"].strip().lower()),
                    "label_yes": int(label_raw),
                    **values,
                }
            )

    return rows


def load_prospective() -> list[dict]:
    rows = []

    required = set(BASELINE_FEATURES) | {
        "rtds_ohlc_return_1m",
    }

    with PROSPECTIVE_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            label_raw = row.get(
                "label_yes",
                "",
            ).strip()

            if label_raw not in {
                "0",
                "1",
            }:
                continue

            values = {feature: optional_float(row.get(feature)) for feature in required}

            if any(value is None for value in values.values()):
                continue

            normalized_yes_mid = optional_float(row.get("normalized_yes_mid"))

            rows.append(
                {
                    "condition_id": (row["condition_id"].strip().lower()),
                    "prediction_timestamp": (row["prediction_timestamp"]),
                    "target_horizon_seconds": int(row["target_horizon_seconds"]),
                    "label_yes": int(label_raw),
                    "normalized_yes_mid": (normalized_yes_mid),
                    **values,
                }
            )

    return rows


def build_matrix(
    rows: list[dict],
    features: tuple[str, ...],
) -> tuple[
    np.ndarray,
    np.ndarray,
]:
    x = np.array(
        [[float(row[feature]) for feature in features] for row in rows],
        dtype=float,
    )

    y = np.array(
        [int(row["label_yes"]) for row in rows],
        dtype=int,
    )

    return (
        x,
        y,
    )


def build_model_b_historical_matrix(
    rows: list[dict],
) -> tuple[
    np.ndarray,
    np.ndarray,
]:
    return build_matrix(
        rows,
        HISTORICAL_MODEL_B_FEATURES,
    )


def build_model_b_prospective_matrix(
    rows: list[dict],
) -> tuple[
    np.ndarray,
    np.ndarray,
]:
    return build_matrix(
        rows,
        PROSPECTIVE_MODEL_B_FEATURES,
    )


def market_metrics(
    rows: list[dict],
) -> dict:
    comparable = [row for row in rows if (row["normalized_yes_mid"] is not None)]

    if not comparable:
        return {
            "rows": 0,
        }

    y = np.array(
        [row["label_yes"] for row in comparable],
        dtype=int,
    )

    p = np.array(
        [row["normalized_yes_mid"] for row in comparable],
        dtype=float,
    )

    return calculate_metrics(
        y,
        p,
    )


def model_vs_market_common_rows(
    rows: list[dict],
    probabilities: np.ndarray,
) -> dict:
    indices = [
        index
        for index, row in enumerate(rows)
        if (row["normalized_yes_mid"] is not None)
    ]

    if not indices:
        return {
            "rows": 0,
        }

    y = np.array(
        [rows[index]["label_yes"] for index in indices],
        dtype=int,
    )

    model_p = np.array(
        [probabilities[index] for index in indices],
        dtype=float,
    )

    market_p = np.array(
        [rows[index]["normalized_yes_mid"] for index in indices],
        dtype=float,
    )

    model_result = calculate_metrics(
        y,
        model_p,
    )

    market_result = calculate_metrics(
        y,
        market_p,
    )

    return {
        "rows": len(indices),
        "model": (model_result),
        "market": (market_result),
        "model_minus_market": {
            "brier": (model_result["brier"] - market_result["brier"]),
            "log_loss": (model_result["log_loss"] - market_result["log_loss"]),
            "accuracy": (model_result["accuracy"] - market_result["accuracy"]),
        },
    }


def main() -> None:
    historical_rows = load_historical()

    prospective_rows = load_prospective()

    if not historical_rows:
        raise RuntimeError("no historical training rows")

    if not prospective_rows:
        raise RuntimeError("no prospective evaluation rows")

    historical_markets = {row["condition_id"] for row in historical_rows}

    prospective_markets = {row["condition_id"] for row in prospective_rows}

    overlap = historical_markets & prospective_markets

    if overlap:
        raise RuntimeError(f"historical/prospective market overlap: {len(overlap)}")

    # -----------------------------
    # MODEL A
    # -----------------------------

    x_a_train, y_train = build_matrix(
        historical_rows,
        BASELINE_FEATURES,
    )

    x_a_test, y_test = build_matrix(
        prospective_rows,
        BASELINE_FEATURES,
    )

    model_a = build_model()

    model_a.fit(
        x_a_train,
        y_train,
    )

    a_probabilities = model_a.predict_proba(x_a_test)[:, 1]

    # -----------------------------
    # MODEL B
    # -----------------------------

    x_b_train, y_b_train = build_model_b_historical_matrix(historical_rows)

    x_b_test, y_b_test = build_model_b_prospective_matrix(prospective_rows)

    if not np.array_equal(
        y_train,
        y_b_train,
    ):
        raise RuntimeError("historical model A/B labels differ")

    if not np.array_equal(
        y_test,
        y_b_test,
    ):
        raise RuntimeError("prospective model A/B labels differ")

    model_b = build_model()

    model_b.fit(
        x_b_train,
        y_b_train,
    )

    b_probabilities = model_b.predict_proba(x_b_test)[:, 1]

    # -----------------------------
    # OVERALL
    # -----------------------------

    a_result = calculate_metrics(
        y_test,
        a_probabilities,
    )

    b_result = calculate_metrics(
        y_test,
        b_probabilities,
    )

    overall_delta = {
        "brier_B_minus_A": (b_result["brier"] - a_result["brier"]),
        "log_loss_B_minus_A": (b_result["log_loss"] - a_result["log_loss"]),
        "accuracy_B_minus_A": (b_result["accuracy"] - a_result["accuracy"]),
    }

    # -----------------------------
    # BY HORIZON
    # -----------------------------

    by_horizon = {}

    for horizon in HORIZONS:
        indices = [
            index
            for index, row in enumerate(prospective_rows)
            if (row["target_horizon_seconds"] == horizon)
        ]

        if not indices:
            continue

        horizon_y = np.array(
            [prospective_rows[index]["label_yes"] for index in indices],
            dtype=int,
        )

        horizon_a = np.array(
            [a_probabilities[index] for index in indices],
            dtype=float,
        )

        horizon_b = np.array(
            [b_probabilities[index] for index in indices],
            dtype=float,
        )

        a_horizon_result = calculate_metrics(
            horizon_y,
            horizon_a,
        )

        b_horizon_result = calculate_metrics(
            horizon_y,
            horizon_b,
        )

        by_horizon[str(horizon)] = {
            "A_BASELINE": (a_horizon_result),
            "B_RTDS_MINUTE": (b_horizon_result),
            "B_minus_A": {
                "brier": (b_horizon_result["brier"] - a_horizon_result["brier"]),
                "log_loss": (
                    b_horizon_result["log_loss"] - a_horizon_result["log_loss"]
                ),
                "accuracy": (
                    b_horizon_result["accuracy"] - a_horizon_result["accuracy"]
                ),
            },
        }

    # -----------------------------
    # MARKET BENCHMARK
    # -----------------------------

    market_result = market_metrics(prospective_rows)

    a_vs_market = model_vs_market_common_rows(
        prospective_rows,
        a_probabilities,
    )

    b_vs_market = model_vs_market_common_rows(
        prospective_rows,
        b_probabilities,
    )

    # -----------------------------
    # COEFFICIENTS
    # -----------------------------

    b_logistic = model_b.named_steps["logistic"]

    b_coefficients = {
        feature: float(coefficient)
        for feature, coefficient in zip(
            PROSPECTIVE_MODEL_B_FEATURES,
            b_logistic.coef_[0],
        )
    }

    # -----------------------------
    # PREDICTION OUTPUT
    # -----------------------------

    prediction_rows = []

    for index, row in enumerate(prospective_rows):
        prediction_rows.append(
            {
                "condition_id": (row["condition_id"]),
                "prediction_timestamp": (row["prediction_timestamp"]),
                "target_horizon_seconds": (row["target_horizon_seconds"]),
                "label_yes": (row["label_yes"]),
                "normalized_yes_mid": (
                    ""
                    if row["normalized_yes_mid"] is None
                    else row["normalized_yes_mid"]
                ),
                "A_BASELINE_probability": (a_probabilities[index]),
                "B_RTDS_MINUTE_probability": (b_probabilities[index]),
            }
        )

    with OUTPUT_PREDICTIONS.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(prediction_rows[0].keys()),
        )

        writer.writeheader()

        writer.writerows(prediction_rows)

    report = {
        "report_version": (REPORT_VERSION),
        "methodology": {
            "historical_training_source": ("p13_enriched_supervised.csv"),
            "prospective_evaluation_source": ("p13_prospective_supervised.csv"),
            "historical_model_B_minute_source": ("Bitstamp completed 1-minute bars"),
            "prospective_model_B_minute_source": (
                "Polymarket RTDS completed 1-minute TWAP bars"
            ),
            "prospective_retraining": (False),
            "hyperparameter_search": (False),
            "calibration": ("none"),
        },
        "historical_training_rows": (len(historical_rows)),
        "historical_training_markets": (len(historical_markets)),
        "prospective_rows": (len(prospective_rows)),
        "prospective_markets": (len(prospective_markets)),
        "market_overlap": (len(overlap)),
        "A_BASELINE": (a_result),
        "B_RTDS_MINUTE": (b_result),
        "B_minus_A": (overall_delta),
        "by_horizon": (by_horizon),
        "market_benchmark": (market_result),
        "A_vs_market_common_rows": (a_vs_market),
        "B_vs_market_common_rows": (b_vs_market),
        "B_standardized_coefficients": (b_coefficients),
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

    print("P13 prospective validation complete")

    print()
    print("TRAINING")

    print(
        "historical_rows=",
        len(historical_rows),
    )

    print(
        "historical_markets=",
        len(historical_markets),
    )

    print()
    print("PROSPECTIVE")

    print(
        "rows=",
        len(prospective_rows),
    )

    print(
        "markets=",
        len(prospective_markets),
    )

    print(
        "historical_market_overlap=",
        len(overlap),
    )

    print()
    print("OVERALL")

    print(
        "A_BASELINE=",
        a_result,
    )

    print(
        "B_RTDS_MINUTE=",
        b_result,
    )

    print(
        "B_MINUS_A=",
        overall_delta,
    )

    print()
    print("BY HORIZON")

    for horizon in HORIZONS:
        result = by_horizon.get(str(horizon))

        if result is None:
            continue

        print()

        print(
            "horizon",
            horizon,
        )

        print(
            " A brier=",
            result["A_BASELINE"]["brier"],
        )

        print(
            " B brier=",
            result["B_RTDS_MINUTE"]["brier"],
        )

        print(
            " delta=",
            result["B_minus_A"],
        )

    print()
    print("MARKET")

    print(
        "market_benchmark=",
        market_result,
    )

    print()

    print(
        "A_vs_market=",
        a_vs_market,
    )

    print()

    print(
        "B_vs_market=",
        b_vs_market,
    )

    print()
    print("B COEFFICIENTS")

    for (
        feature,
        coefficient,
    ) in b_coefficients.items():
        print(
            feature,
            coefficient,
        )

    print()
    print(f"Wrote {OUTPUT_REPORT}")

    print(f"Wrote {OUTPUT_PREDICTIONS}")


if __name__ == "__main__":
    main()
