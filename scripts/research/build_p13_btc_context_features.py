from __future__ import annotations

import csv
import math

from collections import deque
from pathlib import Path
from statistics import mean, pstdev


ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "btc_1m_research_slice.csv"
)

OUTPUT_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "btc_1m_context_features.csv"
)


OUTPUT_FIELDS = (
    "timestamp",
    "observed_at",
    "close",
    "volume",
    "btc_return_1m",
    "btc_return_3m",
    "btc_return_5m",
    "btc_realized_vol_5m",
    "btc_realized_vol_15m",
    "btc_range_5m",
    "btc_volume_zscore_30m",
)


def safe_return(
    current: float,
    previous: float,
) -> float | None:
    if previous == 0.0:
        return None

    return current / previous - 1.0


def realized_volatility(
    prices: list[float],
) -> float | None:
    if len(prices) < 2:
        return None

    returns = []

    for index in range(
        1,
        len(prices),
    ):
        previous = prices[index - 1]

        current = prices[index]

        if previous <= 0.0:
            return None

        returns.append(math.log(current / previous))

    if not returns:
        return None

    return math.sqrt(sum(value * value for value in returns))


def price_range(
    highs: list[float],
    lows: list[float],
    reference_close: float,
) -> float | None:
    if not highs or not lows or reference_close <= 0.0:
        return None

    return (max(highs) - min(lows)) / reference_close


def zscore(
    values: list[float],
    current: float,
) -> float | None:
    if len(values) < 2:
        return None

    center = mean(values)

    spread = pstdev(values)

    if spread == 0.0:
        return 0.0

    return (current - center) / spread


def main() -> None:
    rows = []

    with INPUT_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            rows.append(
                {
                    "timestamp": int(row["timestamp"]),
                    "observed_at": (row["observed_at"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                }
            )

    rows.sort(key=lambda row: row["timestamp"])

    for previous, current in zip(
        rows,
        rows[1:],
    ):
        delta = current["timestamp"] - previous["timestamp"]

        if delta != 60:
            raise RuntimeError(
                "non-contiguous minute history: "
                f"{previous['timestamp']} -> "
                f"{current['timestamp']} "
                f"delta={delta}"
            )

    closes = deque(maxlen=16)

    highs = deque(maxlen=5)

    lows = deque(maxlen=5)

    volumes = deque(maxlen=30)

    output_rows = []

    missing_counts = {
        "btc_return_1m": 0,
        "btc_return_3m": 0,
        "btc_return_5m": 0,
        "btc_realized_vol_5m": 0,
        "btc_realized_vol_15m": 0,
        "btc_range_5m": 0,
        "btc_volume_zscore_30m": 0,
    }

    for row in rows:
        close = row["close"]

        closes.append(close)

        highs.append(row["high"])

        lows.append(row["low"])

        volumes.append(row["volume"])

        close_values = list(closes)

        high_values = list(highs)

        low_values = list(lows)

        volume_values = list(volumes)

        return_1m = (
            safe_return(
                close_values[-1],
                close_values[-2],
            )
            if len(close_values) >= 2
            else None
        )

        return_3m = (
            safe_return(
                close_values[-1],
                close_values[-4],
            )
            if len(close_values) >= 4
            else None
        )

        return_5m = (
            safe_return(
                close_values[-1],
                close_values[-6],
            )
            if len(close_values) >= 6
            else None
        )

        vol_5m = (
            realized_volatility(close_values[-6:]) if len(close_values) >= 6 else None
        )

        vol_15m = (
            realized_volatility(close_values[-16:]) if len(close_values) >= 16 else None
        )

        range_5m = (
            price_range(
                high_values,
                low_values,
                close,
            )
            if len(high_values) >= 5
            else None
        )

        volume_zscore_30m = (
            zscore(
                volume_values[:-1],
                volume_values[-1],
            )
            if len(volume_values) >= 30
            else None
        )

        feature_values = {
            "btc_return_1m": (return_1m),
            "btc_return_3m": (return_3m),
            "btc_return_5m": (return_5m),
            "btc_realized_vol_5m": (vol_5m),
            "btc_realized_vol_15m": (vol_15m),
            "btc_range_5m": (range_5m),
            "btc_volume_zscore_30m": (volume_zscore_30m),
        }

        for (
            name,
            value,
        ) in feature_values.items():
            if value is None:
                missing_counts[name] += 1

        output_rows.append(
            {
                "timestamp": (row["timestamp"]),
                "observed_at": (row["observed_at"]),
                "close": (close),
                "volume": (row["volume"]),
                **feature_values,
            }
        )

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=OUTPUT_FIELDS,
        )

        writer.writeheader()
        writer.writerows(output_rows)

    print("P13 BTC context feature build complete")

    print(
        "input_rows=",
        len(rows),
    )

    print(
        "output_rows=",
        len(output_rows),
    )

    print(
        "first_timestamp=",
        output_rows[0]["observed_at"],
    )

    print(
        "last_timestamp=",
        output_rows[-1]["observed_at"],
    )

    print()

    print("MISSING COUNTS")

    for (
        name,
        count,
    ) in missing_counts.items():
        print(
            name,
            count,
        )

    print()

    print(
        "output=",
        OUTPUT_FILE,
    )


if __name__ == "__main__":
    main()
