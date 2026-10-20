from __future__ import annotations

import csv
import math
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = ROOT / "data" / "normalized" / "p85_strategy_decisions.csv"


EXPECTED_CONFIGS = {
    "ev_000_all_prices": {
        "threshold": 0.00,
        "price_filter": False,
    },
    "ev_002_all_prices": {
        "threshold": 0.02,
        "price_filter": False,
    },
    "ev_005_all_prices": {
        "threshold": 0.05,
        "price_filter": False,
    },
    "ev_000_price_040_060": {
        "threshold": 0.00,
        "price_filter": True,
    },
    "ev_002_price_040_060": {
        "threshold": 0.02,
        "price_filter": True,
    },
    "ev_005_price_040_060": {
        "threshold": 0.05,
        "price_filter": True,
    },
}


EXPECTED_SPLITS = {
    "validation",
    "development_holdout",
}


TOLERANCE = 1e-12


def optional_float(
    value: object,
) -> float | None:
    if value is None:
        return None

    raw = str(value).strip()

    if not raw:
        return None

    return float(raw)


def close(
    left: float,
    right: float,
) -> bool:
    return math.isclose(
        left,
        right,
        rel_tol=0.0,
        abs_tol=TOLERANCE,
    )


def price_allowed(
    price: float,
    *,
    use_filter: bool,
) -> bool:
    if not use_filter:
        return True

    return 0.40 <= price < 0.60


def main() -> None:
    with INPUT_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        rows = list(csv.DictReader(file))

    assert rows, "p85_strategy_decisions.csv is empty"

    configs = {row["strategy_config"] for row in rows}

    assert configs == set(EXPECTED_CONFIGS), f"unexpected config set: {configs}"

    splits = {row["split"] for row in rows}

    assert splits == EXPECTED_SPLITS, f"unexpected split set: {splits}"

    duplicate_key_counter = Counter()

    action_counts = Counter()

    for row in rows:
        config_name = row["strategy_config"]

        config = EXPECTED_CONFIGS[config_name]

        threshold = float(config["threshold"])

        use_filter = bool(config["price_filter"])

        duplicate_key = (
            config_name,
            row["split"],
            row["condition_id"],
            row["prediction_timestamp"],
            row["target_horizon_seconds"],
        )

        duplicate_key_counter[duplicate_key] += 1

        p_yes = float(row["p_yes"])

        p_no = float(row["p_no"])

        yes_ask = float(row["yes_ask"])

        no_ask = float(row["no_ask"])

        yes_ev = float(row["yes_gross_ev_per_share"])

        no_ev = float(row["no_gross_ev_per_share"])

        cost = float(row["estimated_cost_per_share"])

        assert 0.0 <= p_yes <= 1.0

        assert 0.0 <= p_no <= 1.0

        assert close(
            p_no,
            1.0 - p_yes,
        )

        assert close(
            yes_ev,
            p_yes - yes_ask,
        )

        assert close(
            no_ev,
            p_no - no_ask,
        )

        assert close(
            cost,
            0.0,
        )

        candidates = []

        if price_allowed(
            yes_ask,
            use_filter=use_filter,
        ):
            candidates.append(
                (
                    "YES",
                    yes_ask,
                    yes_ev,
                )
            )

        if price_allowed(
            no_ask,
            use_filter=use_filter,
        ):
            candidates.append(
                (
                    "NO",
                    no_ask,
                    no_ev,
                )
            )

        action = row["action"]

        action_counts[
            (
                config_name,
                row["split"],
                action,
            )
        ] += 1

        if not candidates:
            assert action == "SKIP"

            assert row["reason"] == "no_allowed_side"

            assert not (row["selected_side"].strip())

            continue

        expected_side, expected_price, expected_gross = max(
            candidates,
            key=lambda item: (
                item[2],
                item[0],
            ),
        )

        expected_net = expected_gross - cost

        assert row["selected_side"] == expected_side

        assert close(
            float(row["selected_price"]),
            expected_price,
        )

        assert close(
            float(row["selected_gross_ev_per_share"]),
            expected_gross,
        )

        assert close(
            float(row["selected_net_ev_per_share"]),
            expected_net,
        )

        if expected_net >= threshold:
            assert action == "TRADE"

            assert row["reason"] == "positive_strategy_decision"

        else:
            assert action == "SKIP"

            assert row["reason"] == "net_ev_below_threshold"

    duplicates = [key for key, count in duplicate_key_counter.items() if count != 1]

    assert not duplicates, f"duplicate strategy rows: {duplicates[:5]}"

    print("P8.5 validation PASSED")

    print(f"rows={len(rows)}")

    print()

    for config_name in sorted(EXPECTED_CONFIGS):
        for split in (
            "validation",
            "development_holdout",
        ):
            trade_count = action_counts[
                (
                    config_name,
                    split,
                    "TRADE",
                )
            ]

            skip_count = action_counts[
                (
                    config_name,
                    split,
                    "SKIP",
                )
            ]

            print(
                config_name,
                split,
                f"TRADE={trade_count}",
                f"SKIP={skip_count}",
            )


if __name__ == "__main__":
    main()
