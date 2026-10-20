from __future__ import annotations

import csv
import json
import sys

from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(
        0,
        str(SRC),
    )


from polybtc.strategy.expected_value import (
    StrategyAction,
    StrategyParameters,
    evaluate_expected_value,
)


INPUT_FILE = ROOT / "data" / "normalized" / "p8_edge_predictions.csv"

OUTPUT_DECISIONS = ROOT / "data" / "normalized" / "p85_strategy_decisions.csv"

OUTPUT_REPORT = ROOT / "data" / "normalized" / "p85_strategy_report.json"


STRATEGY_VERSION = "p85_strategy_v1"


STRATEGY_CONFIGS = {
    "ev_000_all_prices": StrategyParameters(
        minimum_net_ev_per_share=0.00,
    ),
    "ev_002_all_prices": StrategyParameters(
        minimum_net_ev_per_share=0.02,
    ),
    "ev_005_all_prices": StrategyParameters(
        minimum_net_ev_per_share=0.05,
    ),
    "ev_000_price_040_060": StrategyParameters(
        minimum_net_ev_per_share=0.00,
        minimum_entry_price=0.40,
        maximum_entry_price=0.60,
    ),
    "ev_002_price_040_060": StrategyParameters(
        minimum_net_ev_per_share=0.02,
        minimum_entry_price=0.40,
        maximum_entry_price=0.60,
    ),
    "ev_005_price_040_060": StrategyParameters(
        minimum_net_ev_per_share=0.05,
        minimum_entry_price=0.40,
        maximum_entry_price=0.60,
    ),
}


ESTIMATED_COST_PER_SHARE = 0.0


OUTPUT_FIELDS = (
    "strategy_version",
    "strategy_config",
    "split",
    "condition_id",
    "prediction_timestamp",
    "target_horizon_seconds",
    "label_yes",
    "p_yes",
    "p_no",
    "yes_ask",
    "no_ask",
    "yes_gross_ev_per_share",
    "no_gross_ev_per_share",
    "estimated_cost_per_share",
    "action",
    "selected_side",
    "selected_price",
    "selected_gross_ev_per_share",
    "selected_net_ev_per_share",
    "reason",
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


def load_rows() -> list[dict[str, str]]:
    with INPUT_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def build_decisions(
    rows: list[dict[str, str]],
) -> list[dict]:
    decisions = []

    for row in rows:
        p_yes = optional_float(row.get("probability_yes"))

        yes_ask = optional_float(row.get("yes_ask"))

        no_ask = optional_float(row.get("no_ask"))

        if p_yes is None or yes_ask is None or no_ask is None:
            continue

        for (
            config_name,
            parameters,
        ) in STRATEGY_CONFIGS.items():
            decision = evaluate_expected_value(
                p_yes=p_yes,
                yes_ask=yes_ask,
                no_ask=no_ask,
                estimated_cost_per_share=(ESTIMATED_COST_PER_SHARE),
                parameters=parameters,
            )

            decisions.append(
                {
                    "strategy_version": (STRATEGY_VERSION),
                    "strategy_config": (config_name),
                    "split": (row["split"]),
                    "condition_id": (row["condition_id"]),
                    "prediction_timestamp": (row["prediction_timestamp"]),
                    "target_horizon_seconds": (row["target_horizon_seconds"]),
                    "label_yes": (row["label_yes"]),
                    "p_yes": p_yes,
                    "p_no": (decision.p_no),
                    "yes_ask": yes_ask,
                    "no_ask": no_ask,
                    "yes_gross_ev_per_share": (decision.yes_gross_ev_per_share),
                    "no_gross_ev_per_share": (decision.no_gross_ev_per_share),
                    "estimated_cost_per_share": (decision.estimated_cost_per_share),
                    "action": (decision.action.value),
                    "selected_side": (
                        decision.side.value if decision.side is not None else ""
                    ),
                    "selected_price": (
                        decision.selected_price
                        if decision.selected_price is not None
                        else ""
                    ),
                    "selected_gross_ev_per_share": (
                        decision.selected_gross_ev_per_share
                        if decision.selected_gross_ev_per_share is not None
                        else ""
                    ),
                    "selected_net_ev_per_share": (
                        decision.selected_net_ev_per_share
                        if decision.selected_net_ev_per_share is not None
                        else ""
                    ),
                    "reason": (decision.reason),
                }
            )

    return decisions


def write_decisions(
    decisions: list[dict],
) -> None:
    with OUTPUT_DECISIONS.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=OUTPUT_FIELDS,
        )

        writer.writeheader()
        writer.writerows(decisions)


def summarize_config(
    rows: list[dict],
) -> dict:
    action_counts = Counter(row["action"] for row in rows)

    trade_rows = [row for row in rows if (row["action"] == StrategyAction.TRADE.value)]

    side_counts = Counter(row["selected_side"] for row in trade_rows)

    unique_markets = {row["condition_id"] for row in trade_rows}

    if trade_rows:
        mean_selected_price = sum(
            float(row["selected_price"]) for row in trade_rows
        ) / len(trade_rows)

        mean_gross_ev = sum(
            float(row["selected_gross_ev_per_share"]) for row in trade_rows
        ) / len(trade_rows)

        mean_net_ev = sum(
            float(row["selected_net_ev_per_share"]) for row in trade_rows
        ) / len(trade_rows)

    else:
        mean_selected_price = None
        mean_gross_ev = None
        mean_net_ev = None

    return {
        "rows": len(rows),
        "trade_rows": len(trade_rows),
        "trade_markets": len(unique_markets),
        "action_counts": dict(sorted(action_counts.items())),
        "side_counts": dict(sorted(side_counts.items())),
        "mean_selected_price": (mean_selected_price),
        "mean_gross_ev_per_share": (mean_gross_ev),
        "mean_net_ev_per_share": (mean_net_ev),
    }


def build_report(
    decisions: list[dict],
) -> dict:
    report = {
        "strategy_version": (STRATEGY_VERSION),
        "input": str(INPUT_FILE.relative_to(ROOT)),
        "output": str(OUTPUT_DECISIONS.relative_to(ROOT)),
        "estimated_cost_per_share": (ESTIMATED_COST_PER_SHARE),
        "important_notes": [
            ("This stage produces strategy decisions only."),
            ("No one-entry-per-market position policy is applied."),
            ("No exits, stops, re-entry, sizing, or execution fills are simulated."),
            (
                "The 0.40-0.60 price region "
                "is exploratory and is not "
                "treated as independently "
                "validated."
            ),
            (
                "Transaction cost is set to "
                "zero here. Realistic cost "
                "and execution modeling "
                "belongs to P10."
            ),
        ],
        "configs": {},
    }

    for config_name in STRATEGY_CONFIGS:
        report["configs"][config_name] = {}

        for split in (
            "validation",
            "development_holdout",
        ):
            selected = [
                row
                for row in decisions
                if (row["strategy_config"] == config_name and row["split"] == split)
            ]

            report["configs"][config_name][split] = summarize_config(selected)

    return report


def main() -> None:
    rows = load_rows()

    decisions = build_decisions(rows)

    write_decisions(decisions)

    report = build_report(decisions)

    OUTPUT_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {OUTPUT_DECISIONS}")

    print(f"Wrote {OUTPUT_REPORT}")

    print()
    print(f"decision rows: {len(decisions)}")


if __name__ == "__main__":
    main()
