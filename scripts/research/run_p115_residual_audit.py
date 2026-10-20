from __future__ import annotations

import csv
import json
import math

from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = ROOT / "data" / "normalized" / "p115_residual_dataset.csv"

OUTPUT_REPORT = ROOT / "data" / "normalized" / "p115_residual_audit.json"


REPORT_VERSION = "p115_residual_audit_v1"


SIGNED_BUCKETS = (
    ("LE_-020", None, -0.20),
    ("-020_-010", -0.20, -0.10),
    ("-010_-005", -0.10, -0.05),
    ("-005_-002", -0.05, -0.02),
    ("-002_+002", -0.02, 0.02),
    ("+002_+005", 0.02, 0.05),
    ("+005_+010", 0.05, 0.10),
    ("+010_+020", 0.10, 0.20),
    ("GE_+020", 0.20, None),
)


MAGNITUDE_BUCKETS = (
    ("000_002", 0.00, 0.02),
    ("002_005", 0.02, 0.05),
    ("005_010", 0.05, 0.10),
    ("010_020", 0.10, 0.20),
    ("GE_020", 0.20, None),
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


def optional_float(
    value: object,
) -> float | None:
    if value is None:
        return None

    raw = str(value).strip()

    if not raw:
        return None

    return float(raw)


def brier(
    labels: list[int],
    probabilities: list[float],
) -> float | None:
    if not labels:
        return None

    return sum(
        (probability - label) ** 2
        for label, probability in zip(
            labels,
            probabilities,
        )
    ) / len(labels)


def log_loss(
    labels: list[int],
    probabilities: list[float],
) -> float | None:
    if not labels:
        return None

    epsilon = 1e-15

    total = 0.0

    for label, probability in zip(
        labels,
        probabilities,
    ):
        p = min(
            max(
                probability,
                epsilon,
            ),
            1.0 - epsilon,
        )

        total -= label * math.log(p) + (1 - label) * math.log(1.0 - p)

    return total / len(labels)


def bucket_value(
    value: float,
    buckets: tuple,
) -> str:
    for name, lower, upper in buckets:
        lower_ok = lower is None or value >= lower

        upper_ok = upper is None or value < upper

        if lower_ok and upper_ok:
            return name

    raise RuntimeError(f"value not assigned to bucket: {value}")


def summarize(
    rows: list[dict],
) -> dict:
    if not rows:
        return {
            "rows": 0,
            "markets": 0,
        }

    labels = [row["label_yes"] for row in rows]

    model_probabilities = [row["model_probability"] for row in rows]

    market_probabilities = [row["market_probability"] for row in rows]

    model_brier = brier(
        labels,
        model_probabilities,
    )

    market_brier = brier(
        labels,
        market_probabilities,
    )

    model_log_loss = log_loss(
        labels,
        model_probabilities,
    )

    market_log_loss = log_loss(
        labels,
        market_probabilities,
    )

    directional_rows = [row for row in rows if row["residual_side"] is not None]

    executable_rows = [
        row for row in directional_rows if row["residual_side_ask"] is not None
    ]

    directional_wins = sum(row["residual_side_won"] for row in directional_rows)

    gross_pnl_values = [row["residual_side_gross_pnl"] for row in executable_rows]

    executable_edges = [row["residual_side_model_edge"] for row in executable_rows]

    return {
        "rows": len(rows),
        "markets": len({row["condition_id"] for row in rows}),
        "mean_model_probability": (sum(model_probabilities) / len(model_probabilities)),
        "mean_market_probability": (
            sum(market_probabilities) / len(market_probabilities)
        ),
        "mean_residual": (sum(row["residual"] for row in rows) / len(rows)),
        "mean_absolute_residual": (
            sum(row["absolute_residual"] for row in rows) / len(rows)
        ),
        "label_yes_rate": (sum(labels) / len(labels)),
        "model_brier": (model_brier),
        "market_brier": (market_brier),
        "model_minus_market_brier": (
            model_brier - market_brier
            if (model_brier is not None and market_brier is not None)
            else None
        ),
        "model_log_loss": (model_log_loss),
        "market_log_loss": (market_log_loss),
        "directional_rows": len(directional_rows),
        "directional_win_rate": (
            directional_wins / len(directional_rows) if directional_rows else None
        ),
        "executable_rows": len(executable_rows),
        "mean_model_edge_to_ask": (
            sum(executable_edges) / len(executable_edges) if executable_edges else None
        ),
        "gross_realized_pnl_per_share": (
            sum(gross_pnl_values) / len(gross_pnl_values) if gross_pnl_values else None
        ),
    }


def main() -> None:
    source_rows = load_csv(INPUT_FILE)

    rows = []

    for source in source_rows:
        market_probability = optional_float(source["market_probability"])

        residual = optional_float(source["residual"])

        absolute_residual = optional_float(source["absolute_residual"])

        if market_probability is None or residual is None or absolute_residual is None:
            continue

        label_yes = int(source["label_yes"])

        model_probability = float(source["model_probability"])

        yes_ask = optional_float(source["yes_ask"])

        no_ask = optional_float(source["no_ask"])

        if residual > 0.0:
            residual_side = "YES"
            residual_side_ask = yes_ask

            residual_side_won = 1 if label_yes == 1 else 0

            residual_side_model_edge = (
                model_probability - yes_ask if yes_ask is not None else None
            )

            residual_side_gross_pnl = (
                float(label_yes) - yes_ask if yes_ask is not None else None
            )

        elif residual < 0.0:
            residual_side = "NO"
            residual_side_ask = no_ask

            residual_side_won = 1 if label_yes == 0 else 0

            p_no = 1.0 - model_probability

            residual_side_model_edge = p_no - no_ask if no_ask is not None else None

            residual_side_gross_pnl = (
                float(1 - label_yes) - no_ask if no_ask is not None else None
            )

        else:
            residual_side = None
            residual_side_ask = None
            residual_side_won = 0
            residual_side_model_edge = None
            residual_side_gross_pnl = None

        rows.append(
            {
                "source_split": (source["source_split"]),
                "condition_id": (source["condition_id"]),
                "target_horizon_seconds": int(source["target_horizon_seconds"]),
                "label_yes": (label_yes),
                "model_probability": (model_probability),
                "market_probability": (market_probability),
                "residual": (residual),
                "absolute_residual": (absolute_residual),
                "signed_bucket": (
                    bucket_value(
                        residual,
                        SIGNED_BUCKETS,
                    )
                ),
                "magnitude_bucket": (
                    bucket_value(
                        absolute_residual,
                        MAGNITUDE_BUCKETS,
                    )
                ),
                "residual_side": (residual_side),
                "residual_side_ask": (residual_side_ask),
                "residual_side_won": (residual_side_won),
                "residual_side_model_edge": (residual_side_model_edge),
                "residual_side_gross_pnl": (residual_side_gross_pnl),
            }
        )

    if not rows:
        raise RuntimeError("no market-comparable residual rows")

    grouped_signed = defaultdict(list)
    grouped_magnitude = defaultdict(list)
    grouped_split = defaultdict(list)
    grouped_split_magnitude = defaultdict(list)
    grouped_horizon = defaultdict(list)

    for row in rows:
        grouped_signed[row["signed_bucket"]].append(row)

        grouped_magnitude[row["magnitude_bucket"]].append(row)

        grouped_split[row["source_split"]].append(row)

        grouped_split_magnitude[
            (
                row["source_split"],
                row["magnitude_bucket"],
            )
        ].append(row)

        grouped_horizon[str(row["target_horizon_seconds"])].append(row)

    report = {
        "report_version": (REPORT_VERSION),
        "market_comparable_rows": len(rows),
        "markets": len({row["condition_id"] for row in rows}),
        "overall": summarize(rows),
        "by_source_split": {},
        "by_signed_residual": {},
        "by_residual_magnitude": {},
        "by_source_split_and_magnitude": {},
        "by_horizon": {},
        "important_notes": [
            ("This stage is descriptive only. No residual threshold is selected."),
            (
                "Residual equals walk-forward model "
                "probability minus normalized YES "
                "market-mid probability."
            ),
            (
                "Positive residual means the model "
                "is more bullish on YES than the market."
            ),
            (
                "Negative residual means the model "
                "is more bullish on NO than the market."
            ),
            (
                "Gross realized PnL uses the recorded "
                "executable ask and excludes fees, "
                "slippage, latency, depth constraints, "
                "and position-policy effects."
            ),
            (
                "All rows through 2026-10-01 are "
                "research data and may not be used "
                "as untouched validation for a later "
                "P11.5 strategy."
            ),
        ],
    }

    for split in sorted(grouped_split):
        report["by_source_split"][split] = summarize(grouped_split[split])

    for (
        name,
        _,
        _,
    ) in SIGNED_BUCKETS:
        selected = grouped_signed.get(
            name,
            [],
        )

        report["by_signed_residual"][name] = summarize(selected)

    for (
        name,
        _,
        _,
    ) in MAGNITUDE_BUCKETS:
        selected = grouped_magnitude.get(
            name,
            [],
        )

        report["by_residual_magnitude"][name] = summarize(selected)

    for split in sorted(grouped_split):
        report["by_source_split_and_magnitude"][split] = {}

        for (
            name,
            _,
            _,
        ) in MAGNITUDE_BUCKETS:
            selected = grouped_split_magnitude.get(
                (
                    split,
                    name,
                ),
                [],
            )

            report["by_source_split_and_magnitude"][split][name] = summarize(selected)

    for horizon in (
        "240",
        "180",
        "120",
        "90",
        "60",
        "30",
    ):
        report["by_horizon"][horizon] = summarize(
            grouped_horizon.get(
                horizon,
                [],
            )
        )

    OUTPUT_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print("P11.5 residual audit complete")

    print()

    print(
        "market-comparable rows=",
        len(rows),
    )

    print(
        "markets=",
        len({row["condition_id"] for row in rows}),
    )

    print()

    print("OVERALL")

    overall = report["overall"]

    print(
        "model Brier=",
        round(
            overall["model_brier"],
            6,
        ),
    )

    print(
        "market Brier=",
        round(
            overall["market_brier"],
            6,
        ),
    )

    print(
        "model-market Brier=",
        round(
            overall["model_minus_market_brier"],
            6,
        ),
    )

    print()

    print("BY RESIDUAL MAGNITUDE")

    for (
        name,
        _,
        _,
    ) in MAGNITUDE_BUCKETS:
        metrics = report["by_residual_magnitude"][name]

        print(
            name,
            "rows=",
            metrics["rows"],
            "model-market Brier=",
            (
                round(
                    metrics["model_minus_market_brier"],
                    6,
                )
                if metrics.get("model_minus_market_brier") is not None
                else None
            ),
            "direction win=",
            (
                round(
                    metrics["directional_win_rate"],
                    4,
                )
                if metrics.get("directional_win_rate") is not None
                else None
            ),
            "gross pnl/share=",
            (
                round(
                    metrics["gross_realized_pnl_per_share"],
                    6,
                )
                if metrics.get("gross_realized_pnl_per_share") is not None
                else None
            ),
        )

    print()

    print("SPLIT CONSISTENCY")

    for split in sorted(report["by_source_split_and_magnitude"]):
        print()
        print(split)

        for (
            name,
            _,
            _,
        ) in MAGNITUDE_BUCKETS:
            metrics = report["by_source_split_and_magnitude"][split][name]

            print(
                " ",
                name,
                "rows=",
                metrics["rows"],
                "gross pnl/share=",
                (
                    round(
                        metrics["gross_realized_pnl_per_share"],
                        6,
                    )
                    if metrics.get("gross_realized_pnl_per_share") is not None
                    else None
                ),
            )

    print()

    print(f"Wrote {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
