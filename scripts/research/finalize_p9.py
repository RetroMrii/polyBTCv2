from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

NORMALIZED = ROOT / "data" / "normalized"


BASELINE_FILE = NORMALIZED / "p9_baseline_trades.csv"

SCALEIN_FILE = NORMALIZED / "p9_scalein_trades.csv"

CASHOUT_FILE = NORMALIZED / "p9_cashout_report.json"

STOPLOSS_FILE = NORMALIZED / "p9_stoploss_report.json"

SECOND_ENTRY_FILE = NORMALIZED / "p9_second_entry_audit.json"

THIRD_ENTRY_FILE = NORMALIZED / "p9_third_entry_audit.json"

REVERSAL_FILE = NORMALIZED / "p9_reversal_audit.json"

OUTPUT_FILE = NORMALIZED / "p9_position_policy_manifest.json"


MANIFEST_VERSION = "p9_policy_manifest_v1"


EXPECTED_SPLITS = {
    "validation",
    "development_holdout",
}


def load_csv(
    path: Path,
) -> list[dict[str, str]]:
    with path.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def require_file(
    path: Path,
) -> None:
    if not path.exists():
        raise RuntimeError(f"missing P9 artifact: {path}")


def validate_baseline(
    rows: list[dict[str, str]],
) -> set[str]:
    assert rows, "baseline artifact is empty"

    keys = set()

    strategy_configs = set()

    for row in rows:
        key = (
            row["strategy_config"],
            row["split"],
            row["condition_id"],
        )

        assert key not in keys, f"duplicate baseline market: {key}"

        keys.add(key)

        strategy_configs.add(row["strategy_config"])

        assert row["split"] in EXPECTED_SPLITS

        assert row["side"] in {"YES", "NO"}

        assert float(row["entry_price"]) >= 0.0

        assert float(row["entry_price"]) <= 1.0

    return strategy_configs


def validate_scalein(
    rows: list[dict[str, str]],
    strategy_configs: set[str],
) -> None:
    assert rows, "scale-in artifact is empty"

    keys = set()

    for row in rows:
        key = (
            row["strategy_config"],
            row["split"],
            row["condition_id"],
        )

        assert key not in keys, f"duplicate scale-in market: {key}"

        keys.add(key)

        assert row["strategy_config"] in strategy_configs

        entry_count = int(row["entry_count"])

        assert entry_count in {1, 2}

        entry_1_price = float(row["entry_1_price"])

        assert 0.0 <= entry_1_price <= 1.0

        if entry_count == 1:
            assert not (row["entry_2_horizon_seconds"].strip())

            assert not (row["entry_2_price"].strip())

        else:
            assert row["entry_2_horizon_seconds"].strip()

            entry_2_price = float(row["entry_2_price"])

            assert 0.0 <= entry_2_price <= 1.0

            assert int(row["entry_2_horizon_seconds"]) < int(
                row["entry_1_horizon_seconds"]
            )

        total_pnl = float(row["total_realized_pnl"])

        pnl_per_share = float(row["realized_pnl_per_share"])

        assert abs(pnl_per_share - (total_pnl / entry_count)) < 1e-12


def main() -> None:
    required_files = (
        BASELINE_FILE,
        SCALEIN_FILE,
        CASHOUT_FILE,
        STOPLOSS_FILE,
        SECOND_ENTRY_FILE,
        THIRD_ENTRY_FILE,
        REVERSAL_FILE,
    )

    for path in required_files:
        require_file(path)

    baseline_rows = load_csv(BASELINE_FILE)

    scalein_rows = load_csv(SCALEIN_FILE)

    strategy_configs = validate_baseline(baseline_rows)

    validate_scalein(
        scalein_rows,
        strategy_configs,
    )

    manifest = {
        "manifest_version": (MANIFEST_VERSION),
        "stage": "P9",
        "stage_status": "complete",
        "strategy_configuration_status": ("not_selected_in_p9"),
        "strategy_configurations": sorted(strategy_configs),
        "selected_position_policy": {
            "maximum_entries_per_market": 2,
            "first_entry": ("first chronological TRADE decision"),
            "second_entry": ("next chronological TRADE decision on the same side"),
            "entry_size_shares": 1.0,
            "exit_policy": ("hold_to_settlement"),
            "cashout": False,
            "stop_loss": False,
            "reversal": False,
            "scale_out": False,
            "opposite_side_signal_action": ("ignore_while_position_open"),
        },
        "research_findings": {
            "one_entry_hold": ("control"),
            "fixed_cashout": ("rejected"),
            "fixed_stop_loss": ("rejected"),
            "second_same_side_entry": ("candidate_supported"),
            "third_same_side_entry": ("not_promoted"),
            "opposite_side_reversal": ("rejected"),
        },
        "important_limitations": [
            (
                "Validation and development "
                "holdout data have already "
                "been inspected repeatedly."
            ),
            (
                "The 0.40-0.60 price region "
                "is exploratory and was "
                "discovered on inspected data."
            ),
            ("P9 results use recorded quotes and normalized shares."),
            (
                "Realistic latency, fill "
                "probability, slippage, fees, "
                "capital limits, and execution "
                "mechanics are deferred to P10."
            ),
            ("P9 selects a position policy, not a final production strategy."),
        ],
        "artifacts": [
            "p9_baseline_trades.csv",
            "p9_baseline_report.json",
            "p9_cashout_trades.csv",
            "p9_cashout_report.json",
            "p9_stoploss_trades.csv",
            "p9_stoploss_report.json",
            "p9_scalein_trades.csv",
            "p9_scalein_report.json",
            "p9_second_entry_audit.json",
            "p9_third_entry_audit.json",
            "p9_reversal_audit.json",
        ],
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print("P9 validation PASSED")

    print(
        "strategy configs:",
        len(strategy_configs),
    )

    print(
        "baseline positions:",
        len(baseline_rows),
    )

    print(
        "scale-in positions:",
        len(scalein_rows),
    )

    print(f"Wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
