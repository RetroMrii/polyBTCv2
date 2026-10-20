from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from sklearn.ensemble import HistGradientBoostingClassifier
from xgboost import XGBClassifier


ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "data" / "models"
BASE = ROOT / "data" / "experiments" / "model_expansion"

DATASET = BASE / "hgb3_expanded_v1.csv"
DATASET_META = BASE / "hgb3_expanded_v1_report.json"
EVAL_REPORT = BASE / "hgb3_expanded_calibration_v1_report.json"
EVAL_PREDICTIONS = BASE / "hgb3_expanded_calibration_v1_predictions.csv"

FEATURES = [
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
]

SEED = 1337
TOLERANCE = 1e-8

MODEL_SPECS = {
    "hgb3_expanded_v1": {
        "directory": "main",
        "prediction_column": "hgb3_raw",
    },
    "xgboost_expanded_v1": {
        "directory": "challengers",
        "prediction_column": "xgboost_raw",
    },
}

EXISTING_MODELS = {
    "baseline": ["p12_shadow_model_v1"],
    "challengers": [
        "p13_hgb4_candidate_v1",
        "p13_hgb3_rtds_native_v1",
    ],
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)


def check_outputs_available() -> None:
    for directory in ("main", "challengers", "baseline"):
        path = MODELS / directory

        if path.exists() and not path.is_dir():
            raise RuntimeError(f"Not a directory: {path}")

    for model_id, spec in MODEL_SPECS.items():
        directory = MODELS / spec["directory"]
        for extension in (".joblib", ".json"):
            path = directory / (model_id + extension)
            if path.exists():
                raise FileExistsError(path)

    for directory, model_ids in EXISTING_MODELS.items():
        for model_id in model_ids:
            for extension in (".joblib", ".json"):
                src = MODELS / (model_id + extension)
                dst = MODELS / directory / (model_id + extension)

                require_file(src)

                if dst.exists():
                    if not dst.is_file():
                        raise RuntimeError(f"Unexpected destination type: {dst}")
                    if sha256(src) != sha256(dst):
                        raise RuntimeError(f"Existing copy differs: {dst}")


def prepare_dataset():
    for path in (
        DATASET,
        DATASET_META,
        EVAL_REPORT,
        EVAL_PREDICTIONS,
    ):
        require_file(path)

    with DATASET_META.open(encoding="utf-8") as file:
        dataset_meta = json.load(file)

    with EVAL_REPORT.open(encoding="utf-8") as file:
        evaluation = json.load(file)

    if sha256(DATASET) != dataset_meta["output_sha256"]:
        raise RuntimeError("Expanded dataset checksum mismatch")

    if sha256(DATASET) != evaluation["input_sha256"]:
        raise RuntimeError("Evaluation used a different dataset")

    if dataset_meta["features"] != FEATURES:
        raise RuntimeError("Dataset feature contract mismatch")

    if evaluation["features"] != FEATURES:
        raise RuntimeError("Evaluation feature contract mismatch")

    if sha256(EVAL_PREDICTIONS) != evaluation["output_predictions_sha256"]:
        raise RuntimeError("Evaluation predictions checksum mismatch")

    if not all(name in evaluation["results"] for name in ("hgb3", "xgboost")):
        raise RuntimeError("HGB3/XGBoost evaluation missing")

    df = pd.read_csv(
        DATASET,
        dtype={"condition_id": "string"},
    )

    df["condition_id"] = df["condition_id"].str.strip().str.lower()

    for column in ("prediction_timestamp", "snapshot_observed_at"):
        df[column] = pd.to_datetime(df[column], utc=True, errors="coerce")
        if df[column].isna().any():
            raise RuntimeError(f"Invalid {column}")

    if (df["snapshot_observed_at"] > df["prediction_timestamp"]).any():
        raise RuntimeError("Future snapshot detected")

    for column in FEATURES + ["label_yes"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    if not np.isfinite(df[FEATURES].to_numpy(dtype=float)).all():
        raise RuntimeError("Invalid model features")

    if not df["label_yes"].isin([0, 1]).all():
        raise RuntimeError("Invalid labels")

    if df.duplicated(["condition_id", "target_horizon_seconds"]).any():
        raise RuntimeError("Duplicate market/horizon")

    if (df.groupby("condition_id")["label_yes"].nunique() != 1).any():
        raise RuntimeError("Conflicting market labels")

    if (df.groupby("condition_id")["source_dataset"].nunique() != 1).any():
        raise RuntimeError("Conflicting source provenance")

    if len(df) != dataset_meta["eligible_rows"]:
        raise RuntimeError("Dataset row count changed")

    markets = (
        df.groupby("condition_id", as_index=False)
        .agg(
            first_prediction=("prediction_timestamp", "min"),
            last_prediction=("prediction_timestamp", "max"),
        )
        .sort_values(["first_prediction", "condition_id"])
        .reset_index(drop=True)
    )

    n = len(markets)
    train_end = int(n * 0.60)
    calibration_end = int(n * 0.80)

    train_markets = markets.iloc[:train_end]
    calibration_markets = markets.iloc[train_end:calibration_end]
    evaluation_markets = markets.iloc[calibration_end:]

    if not (
        train_markets["last_prediction"].max()
        < calibration_markets["first_prediction"].min()
        and calibration_markets["last_prediction"].max()
        < evaluation_markets["first_prediction"].min()
    ):
        raise RuntimeError("Partition timestamps overlap")

    def partition(market_frame):
        return (
            df[df["condition_id"].isin(set(market_frame["condition_id"]))]
            .sort_values(
                [
                    "prediction_timestamp",
                    "condition_id",
                    "target_horizon_seconds",
                ],
                ascending=[True, True, False],
            )
            .reset_index(drop=True)
        )

    train = partition(train_markets)
    calibration = partition(calibration_markets)
    test = partition(evaluation_markets)

    for name, frame in (
        ("train", train),
        ("calibration", calibration),
        ("evaluation", test),
    ):
        actual = evaluation["partitions"][name]

        if len(frame) != actual["rows"]:
            raise RuntimeError(f"{name} row mismatch")

        if frame["condition_id"].nunique() != actual["markets"]:
            raise RuntimeError(f"{name} market mismatch")

        first = frame["prediction_timestamp"].min().isoformat()
        last = frame["prediction_timestamp"].max().isoformat()

        if first != actual["first_prediction"] or last != actual["last_prediction"]:
            raise RuntimeError(f"{name} time boundary mismatch")

    saved = pd.read_csv(
        EVAL_PREDICTIONS,
        dtype={"condition_id": "string"},
    )

    saved["condition_id"] = saved["condition_id"].str.strip().str.lower()
    saved["prediction_timestamp"] = pd.to_datetime(
        saved["prediction_timestamp"],
        utc=True,
        errors="coerce",
    )

    keys = [
        "condition_id",
        "prediction_timestamp",
        "target_horizon_seconds",
    ]

    if saved[keys].duplicated().any():
        raise RuntimeError("Duplicate saved prediction keys")

    if test[keys].duplicated().any():
        raise RuntimeError("Duplicate evaluation keys")

    if len(saved) != len(test):
        raise RuntimeError("Saved evaluation row count mismatch")

    reference = test[keys + ["label_yes"]].merge(
        saved,
        on=keys,
        how="left",
        validate="one_to_one",
        indicator=True,
    )

    if not (reference["_merge"] == "both").all():
        raise RuntimeError("Missing saved evaluation predictions")

    reference = reference.drop(columns="_merge")

    if not np.array_equal(
        reference["label_yes_x"].to_numpy(dtype=int),
        reference["label_yes_y"].to_numpy(dtype=int),
    ):
        raise RuntimeError("Evaluation label mismatch")

    return train, test, reference, evaluation


def make_hgb3():
    return HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_iter=200,
        max_depth=3,
        l2_regularization=1.0,
        random_state=SEED,
    )


def make_xgboost():
    return XGBClassifier(
        n_estimators=200,
        max_depth=3,
        learning_rate=0.05,
        subsample=1.0,
        colsample_bytree=1.0,
        objective="binary:logistic",
        eval_metric="logloss",
        tree_method="hist",
        reg_lambda=1.0,
        random_state=SEED,
        n_jobs=4,
    )


def fit_and_verify(train, test, reference):
    x_train = train[FEATURES].to_numpy(dtype=float)
    y_train = train["label_yes"].to_numpy(dtype=int)
    x_test = test[FEATURES].to_numpy(dtype=float)

    if np.unique(y_train).tolist() != [0, 1]:
        raise RuntimeError("Invalid training class population")

    fitted = {}

    for model_id, spec in MODEL_SPECS.items():
        print("Fitting:", model_id, flush=True)

        if model_id == "hgb3_expanded_v1":
            model = make_hgb3()
        else:
            model = make_xgboost()

        model.fit(x_train, y_train)

        current = model.predict_proba(x_test)[:, 1]
        expected = pd.to_numeric(
            reference[spec["prediction_column"]],
            errors="coerce",
        ).to_numpy(dtype=float)

        if not np.isfinite(current).all() or not np.isfinite(expected).all():
            raise RuntimeError(f"{model_id}: invalid evaluation probabilities")

        max_difference = float(np.max(np.abs(current - expected)))

        print(
            f"  max_prediction_difference={max_difference:.12g}",
            flush=True,
        )

        if max_difference > TOLERANCE:
            raise RuntimeError(
                f"{model_id}: failed prediction reproduction; "
                f"max difference={max_difference}"
            )

        fitted[model_id] = (model, max_difference)

    return fitted


def write_new_artifact(
    model_id,
    model,
    difference,
    train,
    evaluation,
):
    spec = MODEL_SPECS[model_id]
    directory = MODELS / spec["directory"]

    model_path = directory / (model_id + ".joblib")
    metadata_path = directory / (model_id + ".json")

    joblib.dump(model, model_path)

    restored = joblib.load(model_path)

    probe = train[FEATURES].head(10).to_numpy(dtype=float)

    before = model.predict_proba(probe)[:, 1]
    after = restored.predict_proba(probe)[:, 1]

    if not np.allclose(before, after, rtol=0, atol=1e-12):
        model_path.unlink(missing_ok=True)
        raise RuntimeError(f"{model_id}: serialization mismatch")

    model_key = "hgb3" if model_id == "hgb3_expanded_v1" else "xgboost"

    metadata = {
        "model_version": model_id,
        "status": "frozen_shadow_research_candidate",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "role": spec["directory"],
        "model_class": type(model).__name__,
        "model_params": {
            key: (
                value
                if isinstance(
                    value,
                    (str, int, float, bool, type(None)),
                )
                else repr(value)
            )
            for key, value in model.get_params(deep=False).items()
        },
        "features": FEATURES,
        "feature_order_locked": True,
        "training_dataset": str(DATASET.relative_to(ROOT)),
        "training_dataset_sha256": sha256(DATASET),
        "training_markets": int(train["condition_id"].nunique()),
        "training_rows": int(len(train)),
        "first_training_timestamp": (train["prediction_timestamp"].min().isoformat()),
        "last_training_timestamp": (train["prediction_timestamp"].max().isoformat()),
        "training_source_markets": (
            train.groupby("source_dataset")["condition_id"].nunique().to_dict()
        ),
        "evaluation_reference": str(EVAL_REPORT.relative_to(ROOT)),
        "evaluation_predictions_reference": str(EVAL_PREDICTIONS.relative_to(ROOT)),
        "evaluation_raw_metrics": (
            evaluation["results"][model_key]["evaluation"]["all_rows"]["raw"]["metrics"]
        ),
        "prediction_reproduction_max_difference": difference,
        "calibration_policy": {
            "version": "identity_v1",
            "method": "identity",
            "fitted": False,
            "output": "raw_predict_proba_yes",
            "note": (
                "Platt and isotonic worsened retrospective "
                "evaluation; identity does not establish "
                "prospective calibration."
            ),
        },
        "reference_provider_status": "unverified_per_source",
        "frozen_model_sha256": sha256(model_path),
        "production_approved": False,
        "live_trading_approved": False,
    }

    with metadata_path.open("x", encoding="utf-8") as file:
        json.dump(
            metadata,
            file,
            indent=2,
            sort_keys=True,
        )
        file.write("\n")

    print("FROZEN:", model_path)


def copy_existing_models():
    for directory, model_ids in EXISTING_MODELS.items():
        target = MODELS / directory
        target.mkdir(parents=True, exist_ok=True)

        for model_id in model_ids:
            for extension in (".joblib", ".json"):
                source = MODELS / (model_id + extension)
                destination = target / (model_id + extension)

                if destination.exists():
                    if sha256(source) != sha256(destination):
                        raise RuntimeError(f"Conflicting destination: {destination}")
                    print("VERIFIED:", destination)
                    continue

                with destination.open("xb") as output:
                    with source.open("rb") as input_file:
                        shutil.copyfileobj(input_file, output)

                if sha256(source) != sha256(destination):
                    destination.unlink(missing_ok=True)
                    raise RuntimeError(f"Copy verification failed: {destination}")

                print("COPIED:", destination)


def main():
    check_outputs_available()

    train, test, reference, evaluation = prepare_dataset()

    print("FREEZE VALIDATION")
    print("training_markets=", train["condition_id"].nunique())
    print("training_rows=", len(train))
    print("evaluation_markets=", test["condition_id"].nunique())
    print("evaluation_rows=", len(test))

    fitted = fit_and_verify(
        train,
        test,
        reference,
    )

    for directory in ("main", "challengers", "baseline"):
        (MODELS / directory).mkdir(
            parents=True,
            exist_ok=True,
        )

    for model_id, (model, difference) in fitted.items():
        write_new_artifact(
            model_id,
            model,
            difference,
            train,
            evaluation,
        )

    copy_existing_models()

    print()
    print("MODEL DIRECTORY ORGANIZATION COMPLETE")
    print("Root-level frozen originals preserved.")
    print("No model is approved for live trading.")


if __name__ == "__main__":
    main()
