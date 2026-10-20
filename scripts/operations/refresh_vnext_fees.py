"""Explicit metadata refresh, separate from collector and decision processing."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from polybtc.data.fee_policy_cache_vnext import VNextFeePolicyCache
from polybtc.data.polymarket_fees import _validate_condition_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fee-cache", type=Path, required=True)
    parser.add_argument("--condition-id", action="append", required=True)
    args = parser.parse_args()
    try:
        markets = tuple(dict.fromkeys(_validate_condition_id(value) for value in args.condition_id))
    except ValueError as exc:
        parser.error(str(exc))
    cache = VNextFeePolicyCache(args.fee_cache)
    for condition_id in markets:
        policy = cache.refresh(condition_id)
        print(json.dumps(policy.provenance(), sort_keys=True))


if __name__ == "__main__":
    main()
