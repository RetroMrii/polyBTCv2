from __future__ import annotations

import argparse
import logging
import json
import msvcrt
import signal
from contextlib import contextmanager
from functools import partial
from pathlib import Path

from polybtc.data.fee_policy_cache_vnext import VNextFeePolicyCache
from polybtc.shadow.source_verification_vnext import VNextSourceVerificationAdapter
from polybtc.shadow.operating_mode_vnext import (
    OperatingMode, DEFAULT_STATE_DIRS, bind_state_directory, supported_mode,
)
from polybtc.shadow.adapter_vnext import (
    VNextEvaluationAdapter,
)
from polybtc.shadow.collector_bridge_vnext import (
    VNextCollectorBridge,
)
from polybtc.shadow.collector_service_vnext import (
    VNextCollectorService,
    VNextSnapshotHistory,
)
from polybtc.shadow.converter_vnext import (
    convert_v1_tail_row,
)
from polybtc.shadow.csv_tail_vnext import SourceChanged, VNextCSVTailer
from polybtc.shadow.orchestrator_vnext import (
    VNextDecisionOrchestrator,
)
from polybtc.shadow.runner_vnext import (
    MAX_REFERENCE_AGE_MS, MAX_BOOK_AGE_MS,
    VerifiedSources,
    VNextShadowRunner,
)
from polybtc.shadow.service_runtime_vnext import (
    RuntimeConfig,
    VNextServiceRuntime,
)
from polybtc.shadow.stream_driver_vnext import (
    VNextSnapshotStreamDriver, StreamDriverConfig,
)

from polybtc.data.paper_policy_vnext import PAPER_POLICY

DEFAULT_MODEL_PATH = Path("data/models/main/hgb3_expanded_v2.joblib")


from polybtc.shadow.writer_lock_vnext import exclusive_lock


def build_runtime(
    csv_path: Path,
    state_dir: Path,
    model_path: Path,
    fee_cache_path: Path | None = None,
    *,
    mode: OperatingMode = OperatingMode.RESEARCH_SHADOW,
    enable_paper_fills: bool = False,
    evidence_path: Path | None = None,
    poll_interval: float = 0.25,
    clock_confirmation: str | None = None,
    input_path: Path | None = None,
) -> VNextServiceRuntime:
    mode = supported_mode(mode)
    if input_path is not None:
        if mode is not OperatingMode.PAPER_EXECUTION or csv_path is not None:
            raise ValueError('Typed input requires paper mode and no CSV transport')
        input_path=Path(input_path).resolve()
        if not input_path.is_file(): raise ValueError('Typed input store missing')
        for supplied in (evidence_path,fee_cache_path):
            if supplied is not None and Path(supplied).resolve()!=input_path:
                raise ValueError('Typed input owns evidence and fee cache')
        evidence_path=fee_cache_path=input_path
        marker=Path(state_dir)/'paper_layout.json'
        if not marker.is_file() or json.loads(marker.read_text(encoding='utf-8')).get('status')!='complete':
            raise ValueError('Typed paper layout requires a completed validated migration')
        if not (Path(state_dir)/'paper.sqlite3').is_file():
            raise ValueError('Migrated paper store missing; restore state instead of initializing a replacement')
    if type(enable_paper_fills) is not bool:
        raise ValueError("Paper execution selection must be a boolean")
    if enable_paper_fills and mode is not OperatingMode.PAPER_EXECUTION:
        raise ValueError("--enable-paper-fills requires paper_execution mode")
    if mode is OperatingMode.PAPER_EXECUTION:
        if fee_cache_path is None or not Path(fee_cache_path).is_file():
            raise ValueError("Paper mode requires an existing fee cache; refresh it separately")
        target = Path(state_dir).resolve()
        for source in (input_path or csv_path, model_path, fee_cache_path, *([evidence_path] if evidence_path is not None else [])):
            if Path(source).resolve().is_relative_to(target):
                raise ValueError("Paper state must not contain input CSV, model or fee cache")
    state_dir = bind_state_directory(state_dir, mode)
    verifier=VNextSourceVerificationAdapter()
    if evidence_path is not None:
        if mode is not OperatingMode.PAPER_EXECUTION:
            raise ValueError('Paper acquisition evidence requires paper mode')
        from polybtc.shadow.acquisition_evidence import AcquisitionEvidenceStore, PaperAcquisitionVerifier
        verifier=PaperAcquisitionVerifier(AcquisitionEvidenceStore(evidence_path))
    store=None
    if input_path is None:
        tailer=VNextCSVTailer(csv_path=csv_path,state_path=state_dir/'csv_tail.sqlite3',startup='end')
        bridge=VNextCollectorBridge(state_path=state_dir/'receipts.sqlite3')
        history=VNextSnapshotHistory(state_dir/'snapshot_history.sqlite3')
        journal=VNextDecisionOrchestrator(journal_path=state_dir/'decisions.sqlite3')
    else:
        from polybtc.shadow.paper_store_vnext import PaperStore
        from polybtc.shadow.input_stream_vnext import SQLiteInputTailer,InputHistory
        store=PaperStore(state_dir/'paper.sqlite3')
        tailer=SQLiteInputTailer(input_path,store)
        bridge=VNextCollectorBridge(state_path=store.path,store=store)
        history=InputHistory(input_path,store)
        journal=VNextDecisionOrchestrator(journal_path=store.path,store=store)
    from polybtc.shadow.clock_vnext import ClockGuard
    import sqlite3
    from datetime import datetime
    with sqlite3.connect(bridge.path) as receipts:
        receipt_watermark = receipts.execute('SELECT MAX(first_received_at_utc) FROM receipts').fetchone()[0]
    with sqlite3.connect(journal.path) as decisions:
        decision_watermark = decisions.execute('SELECT MAX(processed_at_utc) FROM decisions').fetchone()[0]
    stamps = [datetime.fromisoformat(s) for s in (receipt_watermark, decision_watermark) if s]
    guard = ClockGuard(journal.path, utc=bridge.clock, watermark=max(stamps) if stamps else None, store=store)
    bridge.clock = guard.now
    if clock_confirmation is not None:
        guard.acknowledge(clock_confirmation)

    runner = VNextShadowRunner(
        model_path=model_path,
        ledger_path=store.path if store is not None else state_dir / "trades.sqlite3",
        store=store,
        clock=lambda: bridge.clock(),
    )

    fee_cache = (
        VNextFeePolicyCache(fee_cache_path, readonly=input_path is not None) if fee_cache_path is not None else None
    )

    from polybtc.shadow.coordinator_vnext import VNextEvaluationCoordinator
    driver = VNextEvaluationCoordinator(
        journal=journal,
        runner=runner,
        fee_cache=fee_cache,
        # CSV alone does not retain authenticated upstream evidence. Start with
        # no trusted producers; preserve explicit failure reasons in the journal.
        config=StreamDriverConfig(execution_wait_seconds=PAPER_POLICY.execution_wait_seconds if mode is OperatingMode.PAPER_EXECUTION else 0.0),
        source_verifier=verifier,
        clock=lambda: bridge.clock(),
    )

    service = VNextCollectorService(
        tailer=tailer,
        bridge=bridge,
        history=history,
        driver=driver,
        converter=(lambda row: row.snapshot) if input_path is not None else partial(convert_v1_tail_row, source_file=csv_path.name),
    )
    service.clock_guard = guard

    settlement=None
    if store is not None:
        from polybtc.shadow.settlement_handoff_vnext import SettlementHandoff
        settlement=SettlementHandoff(input_path,store,runner.ledger,lambda: bridge.clock())

    return VNextServiceRuntime(
        service=service,
        maintenance=settlement.run_once if settlement else None,
        clock_guard=guard,
        status_path=state_dir / 'runtime_status.json',
        database_paths=() if store is not None else (tailer.state_path, bridge.path, history.path, journal.path, runner.ledger.path),
        resources=(store,tailer,history,settlement) if store is not None else (),
        operating_configuration=dict(
            checkpoint_unit="input_sequence" if input_path else "csv_bytes",
            csv_path=str(csv_path.resolve()) if csv_path else None, input_path=str(input_path) if input_path else None, state_dir=str(state_dir.resolve()),
            evidence_path=str(evidence_path.resolve()) if evidence_path else None,
            fee_cache_path=str(fee_cache_path.resolve()) if fee_cache_path else None,
            max_reference_age_ms=MAX_REFERENCE_AGE_MS, max_book_age_ms=MAX_BOOK_AGE_MS,
            execution_wait_seconds=driver.config.execution_wait_seconds,
            finalization_grace_seconds=journal.config.finalization_grace_seconds,
        ),
        model_path=model_path,
        # Collect and journal opportunities without
        # asserting unverified trading readiness.
        sources=VerifiedSources(
            reference_source_verified=False,
            yes_book_source_verified=False,
            no_book_source_verified=False,
            fee_policy_verified=False,
        ),
        fee_rate=None,
        config=RuntimeConfig(
            interval_seconds=poll_interval,
            # This arms only the isolated paper simulator, never live execution.
            kill_switch=not enable_paper_fills,
            stop_on_error=True,
            mode=mode,
            paper_execution_enabled=enable_paper_fills,
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode", choices=[mode.value for mode in DEFAULT_STATE_DIRS],
        default=OperatingMode.RESEARCH_SHADOW.value,
        help="Research remains the non-executing default; live mode is unavailable",
    )
    parser.add_argument(
        "--enable-paper-fills", action="store_true",
        help="Explicitly arm hypothetical fills in paper mode; all verification/risk gates still apply",
    )

    parser.add_argument(
        "--csv",
        type=Path,
        required=False,
    )

    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="Mode-specific state directory; paper cannot reuse research state",
    )

    parser.add_argument(
        "--model",
        type=Path,
        default=DEFAULT_MODEL_PATH,
    )

    parser.add_argument(
        "--fee-cache",
        type=Path,
        default=None,
        help="Offline market-specific fee cache; required for paper mode",
    )

    parser.add_argument("--poll-interval", type=float, default=0.25,
                        help="Seconds between runtime cycles; source freshness limits remain fixed")
    parser.add_argument(
        "--once",
        action="store_true",
    )
    parser.add_argument('--status',action='store_true',help='Read-only JSON status; no runtime or network clients')
    parser.add_argument('--live-ledger',type=Path,help='Optional existing live lifecycle database for --status')
    parser.add_argument('--input-db',type=Path,help='Consolidated typed input store; replaces CSV transport and contains fees/evidence')
    parser.add_argument('--evidence-db',type=Path,help='Retained collector evidence for paper mode')
    parser.add_argument('--confirm-clock-event', help='Current incident ID, only after independently verifying OS clock accuracy; resumes with a new full market')

    args = parser.parse_args()
    mode = supported_mode(args.mode)
    if args.enable_paper_fills and mode is not OperatingMode.PAPER_EXECUTION:
        parser.error("--enable-paper-fills requires --mode paper_execution")

    csv_path = args.csv.resolve() if args.csv is not None else None
    state_dir = (args.state_dir or DEFAULT_STATE_DIRS[mode]).resolve()
    model_path = args.model.resolve()
    fee_cache_path = args.fee_cache.resolve() if args.fee_cache is not None else None
    if args.status:
        from polybtc.operations import status_report
        print(json.dumps(status_report(state_dir,model_path,live_ledger=args.live_ledger,
                                       fee_cache=fee_cache_path),sort_keys=True))
        return
    if args.csv is None and args.input_db is None: parser.error('--csv or --input-db is required unless --status is selected')
    if args.csv is not None and args.input_db is not None: parser.error('Choose one input transport')
    if args.input_db is not None:
        if fee_cache_path is None: fee_cache_path=args.input_db.resolve()
        if args.evidence_db is None: args.evidence_db=args.input_db.resolve()
    if args.enable_paper_fills and args.evidence_db is None:
        parser.error('--enable-paper-fills requires --evidence-db from the collector')
    if args.live_ledger is not None: parser.error('--live-ledger is only supported with --status')

    if fee_cache_path is not None and not fee_cache_path.is_file():
        parser.error(f"Fee cache database not found: {fee_cache_path}")
    if mode is OperatingMode.PAPER_EXECUTION and fee_cache_path is None:
        parser.error("Paper mode requires --fee-cache; refresh metadata outside this process")

    if csv_path is not None and not csv_path.is_file():
        parser.error(f"CSV source not found: {csv_path}")

    if not model_path.is_file():
        parser.error(f"Model not found: {model_path}")

    logging.basicConfig(
        level=logging.INFO,
        format=("%(asctime)s %(levelname)s %(name)s %(message)s"),
    )

    try:
        with exclusive_lock(state_dir / "vnext.lock"):
            runtime = build_runtime(
                csv_path,
                state_dir,
                model_path,
                fee_cache_path=fee_cache_path,
                mode=mode,
                enable_paper_fills=args.enable_paper_fills,
                evidence_path=args.evidence_db,
                poll_interval=args.poll_interval,
                clock_confirmation=args.confirm_clock_event,
                input_path=args.input_db,
            )

            previous=signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGTERM,lambda *_:runtime.stop())
            try:
                if args.once:
                    runtime.run_once()
                else:
                    runtime.run_forever()
            finally:
                signal.signal(signal.SIGTERM,previous)
                runtime.stop()
    except (ValueError, SourceChanged) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
