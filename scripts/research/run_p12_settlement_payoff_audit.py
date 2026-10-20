from __future__ import annotations

import csv
import json

from collections import defaultdict
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[2]

HISTORICAL_FILE = ROOT / "data" / "normalized" / "p12_historical_consensus_trades.csv"

PROSPECTIVE_FILE = ROOT / "data" / "shadow" / "p12_shadow_settled_trades.csv"

OUTPUT_REPORT = ROOT / "data" / "shadow" / "p12_settlement_payoff_audit.json"

OUTPUT_ROWS = ROOT / "data" / "shadow" / "p12_settlement_payoff_rows.csv"


REPORT_VERSION = "p12_settlement_payoff_audit_v1"


PRICE_BUCKETS = (
    (0.50, 0.60, "0.50-0.60"),
    (0.60, 0.70, "0.60-0.70"),
    (0.70, 0.80, "0.70-0.80"),
    (0.80, 0.90, "0.80-0.90"),
    (0.90, 0.95, "0.90-0.95"),
    (0.95, 1.01, "0.95-1.00"),
)


def load_csv(
    path: Path,
) -> list[dict[str, str]]:
    with path.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def price_bucket(
    price: float,
) -> str:
    for lower, upper, name in PRICE_BUCKETS:
        if lower <= price < upper:
            return name

    return "OUTSIDE_0.50_1.00"


def normalize_historical(
    rows: list[dict[str, str]],
) -> list[dict]:
    result = []

    for row in rows:
        if int(row["slippage_ticks"]) != 0:
            continue

        execution_price = float(row["execution_price"])

        filled_size = float(row["filled_size"])

        fee = float(row["fee"])

        net_pnl = float(row["net_pnl"])

        result.append(
            {
                "evidence_set": ("HISTORICAL_DIAGNOSTIC"),
                "condition_id": (row["condition_id"]),
                "prediction_timestamp": (row["prediction_timestamp"]),
                "horizon_seconds": int(row["target_horizon_seconds"]),
                "side": (row["side"]),
                "won": int(row["won"]),
                "entry_price": (execution_price),
                "filled_size": (filled_size),
                "fee": (fee),
                "fee_per_share": (fee / filled_size),
                "all_in_cost_per_share": (execution_price + (fee / filled_size)),
                "net_pnl": (net_pnl),
                "net_pnl_per_share": (net_pnl / filled_size),
                "price_bucket": (price_bucket(execution_price)),
            }
        )

    return result


def normalize_prospective(
    rows: list[dict[str, str]],
) -> list[dict]:
    result = []

    for row in rows:
        if int(row["slippage_ticks"]) != 0:
            continue

        execution_price = float(row["execution_price"])

        filled_size = float(row["filled_size"])

        fee = float(row["fee"])

        net_pnl = float(row["net_pnl"])

        result.append(
            {
                "evidence_set": ("PROSPECTIVE_SHADOW"),
                "condition_id": (row["condition_id"]),
                "prediction_timestamp": (row["prediction_timestamp"]),
                "horizon_seconds": int(row["target_horizon_seconds"]),
                "side": (row["side"]),
                "won": int(row["won"]),
                "entry_price": (execution_price),
                "filled_size": (filled_size),
                "fee": (fee),
                "fee_per_share": (fee / filled_size),
                "all_in_cost_per_share": (execution_price + (fee / filled_size)),
                "net_pnl": (net_pnl),
                "net_pnl_per_share": (net_pnl / filled_size),
                "price_bucket": (price_bucket(execution_price)),
            }
        )

    return result


def summarize(
    rows: list[dict],
) -> dict:
    if not rows:
        return {
            "entries": 0,
        }

    wins = sum(row["won"] for row in rows)

    losses = len(rows) - wins

    total_pnl = sum(row["net_pnl"] for row in rows)

    total_shares = sum(row["filled_size"] for row in rows)

    total_cost = sum(
        row["entry_price"] * row["filled_size"] + row["fee"] for row in rows
    )

    winning_rows = [row for row in rows if row["won"] == 1]

    losing_rows = [row for row in rows if row["won"] == 0]

    # With equal payoff of $1/share on a win,
    # the average all-in cost/share is the
    # empirical break-even win frequency for
    # this observed set of entry prices.
    break_even_win_rate = mean([row["all_in_cost_per_share"] for row in rows])

    actual_win_rate = wins / len(rows)

    return {
        "entries": len(rows),
        "wins": (wins),
        "losses": (losses),
        "win_rate": (actual_win_rate),
        "average_entry_price": mean([row["entry_price"] for row in rows]),
        "average_fee_per_share": mean([row["fee_per_share"] for row in rows]),
        "average_all_in_cost_per_share": mean(
            [row["all_in_cost_per_share"] for row in rows]
        ),
        "break_even_win_rate": (break_even_win_rate),
        "win_rate_minus_break_even": (actual_win_rate - break_even_win_rate),
        "average_win_pnl_per_share": (
            mean([row["net_pnl_per_share"] for row in winning_rows])
            if winning_rows
            else None
        ),
        "average_loss_pnl_per_share": (
            mean([row["net_pnl_per_share"] for row in losing_rows])
            if losing_rows
            else None
        ),
        "net_pnl": (total_pnl),
        "net_pnl_per_share": (total_pnl / total_shares),
        "roi": (total_pnl / total_cost if total_cost else None),
    }


def grouped_summary(
    rows: list[dict],
    key_name: str,
) -> dict:
    groups = defaultdict(list)

    for row in rows:
        groups[str(row[key_name])].append(row)

    return {key: summarize(group) for key, group in sorted(groups.items())}


def build_section(
    rows: list[dict],
) -> dict:
    return {
        "overall": summarize(rows),
        "by_price_bucket": grouped_summary(
            rows,
            "price_bucket",
        ),
        "by_side": grouped_summary(
            rows,
            "side",
        ),
        "by_horizon": grouped_summary(
            rows,
            "horizon_seconds",
        ),
    }


def main() -> None:
    historical = normalize_historical(load_csv(HISTORICAL_FILE))

    prospective = normalize_prospective(load_csv(PROSPECTIVE_FILE))

    all_rows = historical + prospective

    if not all_rows:
        raise RuntimeError("no settlement trades available")

    with OUTPUT_ROWS.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(all_rows[0].keys()),
        )

        writer.writeheader()

        writer.writerows(all_rows)

    report = {
        "report_version": (REPORT_VERSION),
        "methodology": {
            "exit_policy": ("hold_to_settlement"),
            "cashout": (False),
            "stop_loss": (False),
            "slippage_scenario": ("0_tick"),
            "fee_accounting": (
                "uses exact fee values already "
                "recorded by the authoritative "
                "historical/prospective settlement "
                "accounting outputs"
            ),
            "parameter_search": (False),
        },
        "historical_diagnostic": (build_section(historical)),
        "prospective_shadow": (build_section(prospective)),
        "combined_descriptive_only": (build_section(all_rows)),
        "important_notes": [
            ("Historical and prospective evidence are reported separately."),
            (
                "Combined results are descriptive "
                "only and must not be treated as "
                "untouched prospective validation."
            ),
            (
                "Price buckets are diagnostic. "
                "No entry-price threshold is selected "
                "from this audit."
            ),
            ("P12 remains frozen after this audit."),
        ],
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

    print("P12 settlement payoff audit complete")

    for title, rows in (
        (
            "HISTORICAL DIAGNOSTIC",
            historical,
        ),
        (
            "PROSPECTIVE SHADOW",
            prospective,
        ),
        (
            "COMBINED DESCRIPTIVE ONLY",
            all_rows,
        ),
    ):
        print()
        print("=" * 72)

        print(title)

        print("=" * 72)

        overall = summarize(rows)

        print()
        print("OVERALL")
        print(overall)

        print()
        print("BY PRICE BUCKET")

        bucket_groups = defaultdict(list)

        for row in rows:
            bucket_groups[row["price_bucket"]].append(row)

        for (
            _lower,
            _upper,
            bucket_name,
        ) in PRICE_BUCKETS:
            bucket_rows = bucket_groups.get(
                bucket_name,
                [],
            )

            print(
                bucket_name,
                summarize(bucket_rows),
            )

        outside = bucket_groups.get(
            "OUTSIDE_0.50_1.00",
            [],
        )

        if outside:
            print(
                "OUTSIDE_0.50_1.00",
                summarize(outside),
            )

        print()
        print("BY SIDE")

        for side in (
            "YES",
            "NO",
        ):
            side_rows = [row for row in rows if row["side"] == side]

            print(
                side,
                summarize(side_rows),
            )

        print()
        print("BY HORIZON")

        for horizon in (
            60,
            30,
        ):
            horizon_rows = [row for row in rows if row["horizon_seconds"] == horizon]

            print(
                horizon,
                summarize(horizon_rows),
            )

    print()
    print(f"Wrote {OUTPUT_ROWS}")
    print(f"Wrote {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
