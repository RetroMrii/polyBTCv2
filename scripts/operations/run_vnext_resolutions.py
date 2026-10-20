from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from polybtc.data.polymarket_metadata import (
    fetch_market_metadata,
)
from polybtc.data.polymarket_resolution import (
    fetch_resolution,
)
from polybtc.data.resolution_validation import (
    LABEL_VERSION,
    RESOLUTION_SOURCE_VERSION,
    validate_resolution,
)
from polybtc.data.schema import ResolutionValidationStatus
from polybtc.shadow.ledger_vnext import VNextShadowLedger
from polybtc.shadow.settlement_vnext import (
    VerifiedResolution,
    VNextSettlementService,
)


LOG = logging.getLogger("polybtc.vnext.resolutions")


from polybtc.data.resolution_sync_vnext import (_utc_now, _read_journal_markets, _evidence_id, sync_once as _sync_once)


def sync_once(**kwargs):
    return _sync_once(**kwargs, metadata_fetcher=fetch_market_metadata,
                      resolution_fetcher=fetch_resolution, validator=validate_resolution)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PolyBTC vNext prospective resolution sync"
    )

    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("data/shadow/vnext_local_live"),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0,
        help="0 = single pass; otherwise repeat every N seconds",
    )

    parser.add_argument('--settle-paper',action='store_true',help='Apply verified outcomes to isolated paper positions')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.limit <= 0 or args.interval < 0:
        parser.error("Invalid limit or interval")

    state_dir = args.state_dir
    if (state_dir / "paper_layout.json").exists():
        parser.error("Consolidated paper settlement is owned by the runner; use collector --paper-state")
    if args.settle_paper:
        from polybtc.shadow.operating_mode_vnext import bind_state_directory, OperatingMode
        bind_state_directory(state_dir,OperatingMode.PAPER_EXECUTION)

    journal_path = state_dir / "decisions.sqlite3"
    ledger_path = state_dir / "trades.sqlite3"
    registry_path = state_dir / "resolutions.sqlite3"

    if not journal_path.is_file():
        parser.error(f"Journal does not exist: {journal_path}")

    if not ledger_path.is_file():
        parser.error(f"Ledger does not exist: {ledger_path}")

    ledger = VNextShadowLedger(ledger_path)

    service = VNextSettlementService(
        registry_path=registry_path,
        ledger=ledger,
    )

    try:
        while True:
            result = sync_once(
                journal_path=journal_path,
                service=service,
                now=_utc_now(),
                limit=args.limit,
            )
            if args.settle_paper:
                for resolution in service.resolutions():
                    settled=service.settle(condition_id=resolution['condition_id'],at=_utc_now())
                    result['paper_'+settled.status]=result.get('paper_'+settled.status,0)+1

            print(
                json.dumps(
                    result,
                    sort_keys=True,
                    indent=2,
                )
            )

            if args.interval == 0:
                break

            time.sleep(args.interval)

    except KeyboardInterrupt:
        LOG.info("Resolution sync interrupted")


if __name__ == "__main__":
    main()
