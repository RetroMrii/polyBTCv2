from __future__ import annotations

import argparse

from pathlib import Path

from polybtc.shadow.runner import (
    run_shadow,
)


ROOT = Path(__file__).resolve().parents[2]


DEFAULT_SNAPSHOTS = ROOT / "data" / "raw" / "v1.1" / "btc_5m_market_snapshots_v1_4.csv"

DEFAULT_MODEL = ROOT / "data" / "models" / "p12_shadow_model_v1.joblib"

DEFAULT_OUTPUT = ROOT / "data" / "shadow" / "p12_consensus_shadow_decisions.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Run the PolyBTC P12 prospective shadow strategy.")
    )

    parser.add_argument(
        "--snapshots",
        type=Path,
        default=DEFAULT_SNAPSHOTS,
    )

    parser.add_argument(
        "--model",
        type=Path,
        default=DEFAULT_MODEL,
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    result = run_shadow(
        snapshots_path=(args.snapshots),
        model_path=(args.model),
        output_path=(args.output),
    )

    print("P12 shadow run complete")

    print(
        "snapshots=",
        result.snapshots,
    )

    print(
        "candidate_horizons=",
        result.candidate_horizons,
    )

    print(
        "newly_written=",
        result.newly_written,
    )

    print(
        "trades=",
        result.trades,
    )

    print(
        "abstains=",
        result.abstains,
    )


if __name__ == "__main__":
    main()
