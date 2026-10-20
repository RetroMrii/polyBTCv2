"""Copy-only S4 migration; stop collector/runtime/settlement writers first."""

import argparse, json
from pathlib import Path
from polybtc.shadow.migration_vnext import migrate
from scripts.operations.run_vnext_shadow import exclusive_lock


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state-dir", type=Path, required=True)
    p.add_argument("--evidence-db", type=Path, required=True)
    p.add_argument("--fee-cache", type=Path, required=True)
    p.add_argument("--destination", type=Path, required=True)
    p.add_argument(
        "--writers-stopped",
        action="store_true",
        help="Confirm collector, paper runner and settlement workers are stopped",
    )
    a = p.parse_args()
    if not a.writers_stopped:
        p.error("Stop all source writers and supply --writers-stopped")
    with exclusive_lock(a.state_dir / "vnext.lock"):
        print(
            json.dumps(
                migrate(
                    state_dir=a.state_dir,
                    evidence_db=a.evidence_db,
                    fee_cache=a.fee_cache,
                    destination=a.destination,
                ),
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
