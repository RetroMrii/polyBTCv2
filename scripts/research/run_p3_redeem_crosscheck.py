from __future__ import annotations

import csv
import json

from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

RAW_HISTORY = ROOT / "data" / "raw" / "v1.1" / "Polymarket-History-2026-09-16.csv"

MARKETS_FILE = ROOT / "data" / "normalized" / "markets.csv"

RESOLUTIONS_FILE = ROOT / "data" / "normalized" / "market_resolutions.csv"

OUTPUT_CSV = ROOT / "data" / "normalized" / "p3_redeem_crosscheck.csv"

OUTPUT_REPORT = ROOT / "data" / "normalized" / "p3_redeem_crosscheck_report.json"


def normalize_outcome(
    value: str | None,
) -> str | None:
    if value is None:
        return None

    normalized = value.strip().upper()

    if normalized in {"UP", "YES"}:
        return "YES"

    if normalized in {"DOWN", "NO"}:
        return "NO"

    return None


def load_markets() -> dict[str, dict[str, str]]:
    with MARKETS_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        rows = list(csv.DictReader(file))

    by_question: dict[str, dict[str, str]] = {}

    for row in rows:
        question = row["question"].strip()

        if not question:
            continue

        if question in by_question:
            raise RuntimeError(f"duplicate market question detected: {question}")

        by_question[question] = row

    return by_question


def load_resolutions() -> dict[str, dict[str, str]]:
    with RESOLUTIONS_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        rows = list(csv.DictReader(file))

    by_condition_id: dict[
        str,
        dict[str, str],
    ] = {}

    for row in rows:
        condition_id = row["condition_id"].strip().lower()

        if condition_id in by_condition_id:
            raise RuntimeError(f"duplicate resolution condition_id: {condition_id}")

        by_condition_id[condition_id] = row

    return by_condition_id


def load_redeems() -> list[dict[str, str]]:
    with RAW_HISTORY.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        rows = csv.DictReader(file)

        return [row for row in rows if row["action"].strip().upper() == "REDEEM"]


def main() -> None:
    markets_by_question = load_markets()
    resolutions = load_resolutions()
    redeems = load_redeems()

    output_rows: list[dict[str, object]] = []

    matched = 0
    outcome_matches = 0
    outcome_mismatches = 0
    outside_dataset = 0
    invalid_redeem_outcome = 0

    for redeem in redeems:
        market_name = redeem["marketName"].strip()

        wallet_outcome = normalize_outcome(redeem.get("tokenName"))

        market = markets_by_question.get(market_name)

        if market is None:
            outside_dataset += 1

            output_rows.append(
                {
                    "market_name": market_name,
                    "condition_id": "",
                    "wallet_token_name": (
                        redeem.get(
                            "tokenName",
                            "",
                        )
                    ),
                    "wallet_outcome": (wallet_outcome or ""),
                    "authoritative_outcome": "",
                    "authoritative_label_yes": "",
                    "crosscheck_status": ("OUTSIDE_DATASET"),
                    "usdc_amount": redeem.get(
                        "usdcAmount",
                        "",
                    ),
                    "token_amount": redeem.get(
                        "tokenAmount",
                        "",
                    ),
                    "redeem_timestamp": redeem.get(
                        "timestamp",
                        "",
                    ),
                    "transaction_hash": redeem.get(
                        "hash",
                        "",
                    ),
                }
            )

            continue

        condition_id = market["condition_id"].strip().lower()

        resolution = resolutions.get(condition_id)

        if resolution is None:
            raise RuntimeError(f"market exists without P3 resolution: {condition_id}")

        matched += 1

        authoritative_outcome = resolution["winning_outcome"].strip().upper()

        if wallet_outcome is None:
            status = "INVALID_REDEEM_OUTCOME"
            invalid_redeem_outcome += 1

        elif wallet_outcome == authoritative_outcome:
            status = "MATCH"
            outcome_matches += 1

        else:
            status = "MISMATCH"
            outcome_mismatches += 1

        output_rows.append(
            {
                "market_name": market_name,
                "condition_id": condition_id,
                "wallet_token_name": redeem.get(
                    "tokenName",
                    "",
                ),
                "wallet_outcome": (wallet_outcome or ""),
                "authoritative_outcome": (authoritative_outcome),
                "authoritative_label_yes": (resolution["label_yes"]),
                "crosscheck_status": status,
                "usdc_amount": redeem.get(
                    "usdcAmount",
                    "",
                ),
                "token_amount": redeem.get(
                    "tokenAmount",
                    "",
                ),
                "redeem_timestamp": redeem.get(
                    "timestamp",
                    "",
                ),
                "transaction_hash": redeem.get(
                    "hash",
                    "",
                ),
            }
        )

    fieldnames = [
        "market_name",
        "condition_id",
        "wallet_token_name",
        "wallet_outcome",
        "authoritative_outcome",
        "authoritative_label_yes",
        "crosscheck_status",
        "usdc_amount",
        "token_amount",
        "redeem_timestamp",
        "transaction_hash",
    ]

    with OUTPUT_CSV.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()
        writer.writerows(output_rows)

    report = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "total_redeem_rows": len(redeems),
        "matched_to_p3_markets": matched,
        "outcome_matches": outcome_matches,
        "outcome_mismatches": (outcome_mismatches),
        "invalid_redeem_outcome": (invalid_redeem_outcome),
        "outside_p3_dataset": (outside_dataset),
        "authoritative_labels_changed": 0,
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

    print(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
