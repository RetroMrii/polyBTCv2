import json
import math
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

from .data import Reader, freshness, now, number, probability, read_db, stamp
from .schemas import (
    Decision,
    DecisionPage,
    Health,
    Market,
    Overview,
    Performance,
    Portfolio,
    Reason,
    Resolution,
    ResolutionPage,
    Source,
    Telemetry,
    TelemetryPoint,
)

HORIZONS = (240, 180, 120, 90, 60, 30)
REASON_CATALOG = json.loads(Path(__file__).with_name("reasons.json").read_text(encoding="utf-8"))
EXPLANATIONS = {
    "unverified_input_provenance": "Safety gate: reference, book or fee provenance was not independently verified. This does not indicate a process failure.",
    "unverified_execution_provenance": "Safety gate: the execution quote or fee provenance was not independently verified. No hypothetical fill was authorized.",
    "missing_execution_snapshot": "No separate execution-time snapshot was available after the prediction target.",
    "missing_horizon": "No eligible historical observation was available for this scheduled horizon.",
    "stale_horizon": "The nearest eligible snapshot was too old for the scheduled prediction target.",
    "snapshot_arrived_after_target": "The observation arrived after the prediction cutoff and cannot be used causally.",
    "missing_reference_return_30s": "The causal 30-second reference-price history was insufficient to construct the model feature.",
    "stale_reference": "The reference source exceeded the effective reference-age limit at a runner or strategy freshness check. Consult the runtime configuration for the active limit.",
    "stale_market_books": "One or both books exceeded the runner limit of 500 ms.",
    "future_source_timestamp": "A source timestamp was later than evaluation time. Negative ages are preserved.",
    "shadow_full_fill": "The journal recorded a hypothetical full fill. This is not a real order.",
    "evaluation_claimed": "The runner claimed this horizon; a final result may still be pending.",
}
STRATEGY = {
    "market_direction_neutral",
    "model_market_disagreement",
    "model_direction_neutral",
    "probability_gap_too_large",
    "insufficient_depth",
    "price_ceiling_exceeded",
    "insufficient_net_ev",
    "before_target_horizon",
    "market_already_expired",
    "market_already_entered",
}


def reason_info(code):
    if "provenance" in code or "verification" in code:
        category = "Execution authorization"
    elif any(word in code for word in ("causal", "after_target", "future", "predates", "mismatch")):
        category = "Invalid causal inputs"
    elif code.startswith(("missing", "stale")) or "not_available" in code:
        category = "Telemetry unavailable"
    elif code in STRATEGY:
        category = "Strategy abstention"
    elif any(word in code for word in ("error", "exception", "failed")):
        category = "Operational failure"
    elif any(word in code for word in ("risk", "limit", "kill_switch")):
        category = "Risk gate"
    elif code in ("shadow_full_fill", "positive_net_ev", "shadow_risk_approved"):
        category = "Authorized shadow outcome"
    else:
        category = "Journal / validation"
    return Reason(
        category=category,
        explanation=EXPLANATIONS.get(
            code,
            code.replace("_", " ").capitalize()
            + ". Recorded by the trading pipeline; consult the exact code below.",
        ),
    )


class Monitor:
    def __init__(self, settings):
        self.reader = Reader(settings)
        self.settings = settings

    def market_row(self, row, at):
        values = {
            key: number(row.get(key))
            for key in (
                "btc_price",
                "strike",
                "seconds_to_expiry",
                "yes_bid",
                "yes_ask",
                "no_bid",
                "no_ask",
                "yes_bid_size",
                "yes_ask_size",
                "no_bid_size",
                "no_ask_size",
                "reference_age_ms",
                "yes_book_age_ms",
                "no_book_age_ms",
            )
        }
        warnings = []
        for key in ("yes_bid", "yes_ask", "no_bid", "no_ask"):
            if values[key] is not None and probability(values[key]) is None:
                warnings.append(key + " is outside [0, 1]")
                values[key] = None
        dates = {
            key: stamp(row.get(key))
            for key in (
                "observed_at",
                "market_end_at",
                "reference_timestamp",
                "yes_book_timestamp",
                "no_book_timestamp",
            )
        }
        expiry = dates["market_end_at"]
        active = bool(expiry and expiry - timedelta(minutes=5) <= at < expiry and dates["observed_at"] <= at)
        health = {}
        for key, limit in [("reference", 2), ("yes_book", 0.5), ("no_book", 0.5)]:
            health[key] = freshness(
                row.get(key + "_timestamp"), limit, "Current wall-clock source age; runner threshold.", at
            )
            recorded = values[key + "_age_ms"]
            if recorded is None:
                warnings.append(key + ": collector-recorded source age missing")
            elif recorded < 0:
                warnings.append(f"{key}: future-dated at observation ({recorded:.1f} ms)")
            elif recorded > limit * 1000:
                warnings.append(f"{key}: stale at observation ({recorded:.1f} ms)")
            if health[key].state != "ok":
                warnings.append(key + ": " + health[key].state + " source timestamp now")
        mids = []
        for side in ("yes", "no"):
            bid, ask = values[side + "_bid"], values[side + "_ask"]
            values[side + "_spread"] = ask - bid if bid is not None and ask is not None else None
            if bid is not None and ask is not None and bid > ask:
                warnings.append(side + ": crossed book")
                mids.append(None)
            else:
                mids.append((bid + ask) / 2 if bid is not None and ask is not None else None)
        baseline = mids[0] / sum(mids) if None not in mids and sum(mids) > 0 else None
        return Market(
            market_id=row["market_id"],
            question=row.get("question", ""),
            **values,
            **{k: v.isoformat() if v else None for k, v in dates.items()},
            active=active,
            market_probability_yes=baseline,
            distance=values["btc_price"] - values["strike"]
            if values["btc_price"] is not None and values["strike"] is not None
            else None,
            warnings=warnings,
            source_health=health,
        )

    def telemetry(self, minutes=15):
        rows, source = self.reader.telemetry()
        at = now()
        ordered = sorted(rows or [], key=lambda r: stamp(r["observed_at"]))
        # Prefer a currently active market; retain latest observation explicitly if all expired.
        active = [
            r
            for r in ordered
            if stamp(r.get("market_end_at"))
            and stamp(r["market_end_at"]) - timedelta(minutes=5) <= at < stamp(r["market_end_at"])
            and stamp(r["observed_at"]) <= at
        ]
        current_raw = (active or ordered)[-1] if ordered else None
        current = self.market_row(current_raw, at) if current_raw else None
        if current and source.state == "ok":
            source = freshness(
                current.observed_at,
                5,
                "Recent observations indicate activity, not verified process status.",
                at,
            )
        elif current is None and source.state == "ok":
            source = Source(
                state="missing", detail="No complete observations with a valid timestamp are available."
            )
        cutoff = at - timedelta(minutes=minutes)
        history = [
            TelemetryPoint(
                market_id=r["market_id"], observed_at=r["observed_at"], btc_price=number(r.get("btc_price"))
            )
            for r in ordered
            if stamp(r["observed_at"]) >= cutoff and stamp(r["observed_at"]) <= at
        ]
        return Telemetry(
            current=current,
            rows=history[-1800:],
            source=source,
            scope=f"Actual CSV observations only. Up to {minutes} minutes / 1,800 points from the last 2 MiB; chart gaps over five seconds are broken.",
            generated_at=at.isoformat(),
        )

    def resolutions(self):
        rows, source = self.reader.resolutions()
        valid = []
        for row in rows or []:
            try:
                item = Resolution.model_validate(row)
                if stamp(item.resolved_at_utc) is None or not item.evidence_id or not item.evidence_source:
                    raise ValueError("Invalid evidence")
                valid.append(item)
            except ValueError:
                source = Source(
                    state="error", detail="Invalid registry rows excluded; resolution coverage is incomplete."
                )
        return ResolutionPage(
            rows=sorted(valid, key=lambda r: r.resolved_at_utc, reverse=True),
            source=source,
            scope="Latest 2,000 registered outcomes. VERIFIED does not mean a trade was settled.",
        )

    def decision_rows(self):
        raw, source = self.reader.decisions()
        resolutions = self.resolutions()
        labels = {r.condition_id.lower(): r for r in resolutions.rows}
        result = []
        for original in raw or []:
            row = dict(original)
            warnings = []
            for key in (
                "model_probability_yes",
                "prediction_market_probability_yes",
                "market_probability_yes",
            ):
                value = probability(row.get(key))
                if row.get(key) is not None and value is None:
                    warnings.append(key + " is invalid; excluded")
                row[key] = value
            for key in (
                "target_at_utc",
                "processed_at_utc",
                "snapshot_observed_at_utc",
                "snapshot_ingested_at_utc",
            ):
                if row.get(key) and stamp(row[key]) is None:
                    warnings.append(key + " is an invalid timestamp")
            p, q = row["model_probability_yes"], row["prediction_market_probability_yes"]
            label = labels.get(row["condition_id"].lower())
            result.append(
                Decision(
                    **row,
                    model_probability_no=1 - p if p is not None else None,
                    probability_difference=p - q if p is not None and q is not None else None,
                    reason_info=reason_info(row["reason"]),
                    validation_warnings=warnings,
                    verified_outcome=label.label_yes if label else None,
                    outcome_state=("registered" if resolutions.source.state == "ok" else "cached registry")
                    if label
                    else "No registered outcome in available registry window",
                )
            )
        return result, source

    def decisions(
        self,
        page=1,
        page_size=25,
        search="",
        market="",
        horizon=None,
        reason="",
        status="",
        availability="all",
        outcome="all",
        minimum=None,
        maximum=None,
        after=None,
        before=None,
        sort="target_at_utc",
        direction="desc",
    ):
        rows, source = self.decision_rows()
        reasons = sorted(set(REASON_CATALOG) | {r.reason for r in rows})
        selected = []
        for r in rows:
            p = r.model_probability_yes
            if search and search.lower() not in (r.condition_id + " " + r.reason + " " + r.status).lower():
                continue
            if market and r.condition_id.lower() != market.lower():
                continue
            if horizon is not None and r.horizon_seconds != horizon:
                continue
            if reason and r.reason != reason:
                continue
            if status and r.status != status:
                continue
            if availability == "available" and p is None:
                continue
            if availability == "missing" and p is not None:
                continue
            if outcome == "verified" and r.verified_outcome is None:
                continue
            if outcome == "missing" and r.verified_outcome is not None:
                continue
            if minimum is not None and (p is None or p < minimum):
                continue
            if maximum is not None and (p is None or p > maximum):
                continue
            target = stamp(r.target_at_utc)
            if after and (target is None or target < after):
                continue
            if before and (target is None or target > before):
                continue
            selected.append(r)
        selected.sort(
            key=lambda r: (getattr(r, sort) is not None, getattr(r, sort) or 0), reverse=direction == "desc"
        )
        return DecisionPage(
            rows=selected[(page - 1) * page_size : page * page_size],
            total=len(selected),
            page=page,
            page_size=page_size,
            source=source,
            reasons=reasons,
            scope=f"Search, sorting and totals cover the latest {self.settings.recent_limit:,} journal records (bounded read).",
        )

    def portfolio(self):
        def load():
            with read_db(self.settings.trades) as db:
                entries = [dict(r) for r in db.execute("SELECT * FROM entries ORDER BY id DESC LIMIT 2001")]
                if len(entries) > 2000:
                    raise ValueError("Portfolio exceeds bounded audit window")
                # Return data only, never invoke ledger/executor constructors.
                contexts = {
                    r["entry_id"]: json.loads(r["context_json"])
                    for r in db.execute("SELECT * FROM entry_decision_context LIMIT 2001")
                }
                events = defaultdict(list)
                for r in db.execute("SELECT * FROM entry_events ORDER BY event_id DESC LIMIT 10001"):
                    events[r["entry_id"]].insert(0, dict(r))
            return entries, contexts, events

        value, source = self.reader.cached("portfolio", 15, load)
        if value is None:
            return Portfolio(
                source=source, detail="Trading ledger unavailable. No profitability metrics inferred."
            )
        entries, contexts, events = value
        if not entries:
            return Portfolio(
                source=source,
                filled=0,
                settled=0,
                realized_pnl=0.0 if source.state == "ok" else None,
                exposure=0.0 if source.state == "ok" else None,
                pending=0,
                reserved=0.0 if source.state == "ok" else None,
                fees=0.0 if source.state == "ok" else None,
                total_fills=0,
                detail="No hypothetical fills recorded. Empty ledger; win rate is unavailable until settlements exist.",
            )
        decisions, decision_source = self.decision_rows()
        resolutions = self.resolutions()
        labels = {r.condition_id: r for r in resolutions.rows}
        error = None
        settled, filled, pnl, exposure, wins = 0, 0, 0.0, 0.0, 0
        reserved, fees = 0.0, 0.0
        settlements = []
        try:
            if decision_source.state != "ok" or resolutions.source.state != "ok" or source.state != "ok":
                raise ValueError("Audit sources unavailable or cached")
            for entry in entries:
                state = entry["status"]
                if state == "PENDING":
                    reserve = number(entry["reserved_cost"])
                    if reserve is None or reserve < 0:
                        raise ValueError("Invalid reservation")
                    exposure += reserve
                    reserved += reserve
                if state not in ("FILLED", "SETTLED"):
                    continue
                price, size, fee = (number(entry[k]) for k in ("execution_price", "filled_size", "entry_fee"))
                if (
                    price is None
                    or size is None
                    or fee is None
                    or not 0 < price <= 0.7
                    or size <= 0
                    or fee < 0
                ):
                    raise ValueError("Invalid fill amounts")
                fees += fee
                matches = [
                    r
                    for r in decisions
                    if r.condition_id == entry["condition_id"] and r.status == "SHADOW_FILLED"
                ]
                context = contexts.get(entry["id"], {})
                audit = events.get(entry["id"], [])
                expected_events = ["ENTRY_RESERVED", "ENTRY_FILLED"] + (
                    ["ENTRY_SETTLED"] if state == "SETTLED" else []
                )
                if len(matches) != 1 or [e["event_type"] for e in audit] != expected_events:
                    raise ValueError("Missing journal fill or complete event audit in bounded window")
                decision = matches[0]
                if (
                    not decision.snapshot_id
                    or stamp(decision.target_at_utc) is None
                    or context.get("snapshot_id") != decision.snapshot_id
                    or stamp(context.get("prediction_timestamp_utc")) != stamp(decision.target_at_utc)
                    or context.get("strategy_action") != "BUY_" + entry["side"]
                    or not math.isclose(price, decision.execution_price or -1, abs_tol=1e-9)
                ):
                    raise ValueError("Fill context mismatch")
                if state == "FILLED":
                    filled += 1
                    exposure += price * size + fee
                else:
                    resolution = labels.get(entry["condition_id"])
                    if (
                        not resolution
                        or resolution.settlement_status != "SETTLED"
                        or resolution.label_yes != entry["label_yes"]
                    ):
                        raise ValueError("Settlement not reconciled with registry")
                    won = (entry["side"] == "YES") == bool(entry["label_yes"])
                    expected = (size if won else 0) - price * size - fee
                    recorded = number(entry["realized_pnl"])
                    event = json.loads(audit[-1]["payload_json"])
                    event_pnl = number(event.get("realized_pnl"))
                    if (
                        recorded is None
                        or event_pnl is None
                        or event.get("label_yes") != entry["label_yes"]
                        or not math.isclose(expected, recorded, abs_tol=1e-7)
                        or not math.isclose(expected, event_pnl, abs_tol=1e-7)
                    ):
                        raise ValueError("Settlement P&L audit mismatch")
                    date = stamp(entry.get("settled_at_utc"))
                    if date is None:
                        raise ValueError("Settlement timestamp missing")
                    settlements.append((date.isoformat(), entry["id"], recorded))
                    settled += 1
                    pnl += recorded
                    wins += won
        except (ValueError, KeyError, TypeError) as exc:
            error = str(exc)
        history, cumulative = [], 0.0
        if not error:
            for date, entry_id, realized in sorted(settlements):
                cumulative += realized
                history.append(dict(time=date, entry_id=entry_id, pnl=cumulative))
        return Portfolio(
            source=source,
            entries=entries,
            pending=sum(e.get("status") == "PENDING" for e in entries),
            reserved=reserved if not error else None,
            fees=fees if not error else None,
            total_fills=filled + settled if not error else None,
            pnl_history=history,
            filled=sum(e.get("status") == "FILLED" for e in entries),
            settled=sum(e.get("status") == "SETTLED" for e in entries),
            realized_pnl=pnl if not error else None,
            exposure=exposure if not error else None,
            win_rate=wins / settled if settled and not error else None,
            detail=("Metrics withheld: " + error)
            if error
            else "Hypothetical only. Net realized P&L includes recorded entry fees; each fill and settlement is cross-checked against journal, context, events and registry.",
        )

    def health(self, telemetry=None):
        telemetry = telemetry or self.telemetry()
        rows, source = self.decision_rows()
        latest = max((r.processed_at_utc for r in rows), default=None)
        sources = {
            "collector": telemetry.source,
            "journal_read": source,
            "journal_activity": freshness(
                latest,
                300,
                "A scheduled decision may arrive only once per horizon. Process state is not verified.",
            ),
            "registry_read": self.resolutions().source,
            "ledger_read": self.portfolio().source,
            "report_read": self.reader.report()[1],
            "backend": Source(
                state="ok", timestamp=now().isoformat(), detail="API responding; loopback-only service."
            ),
        }
        heartbeat, heartbeat_source = self.reader.runtime()
        process_status = "Unknown — runtime heartbeat unavailable."
        if heartbeat and heartbeat_source.state == "ok":
            heartbeat_source = freshness(
                heartbeat.get("observed_at"), 5, "Runtime heartbeat; not OS process inspection."
            )
            if heartbeat_source.state == "ok":
                process_status = (
                    "Runtime reports "
                    + heartbeat["state"]
                    + (
                        " · paper fills armed"
                        if heartbeat.get("mode") == "paper_execution"
                        and heartbeat.get("kill_switch") is False
                        and heartbeat.get("state") == "running"
                        else " · execution disabled"
                    )
                )
            else:
                process_status = (
                    "Unknown — " + heartbeat_source.state + " heartbeat; last reported " + heartbeat["state"]
                )
        sources["runtime"] = heartbeat_source
        registry = self.resolutions()
        sources["last_resolution"] = freshness(
            max((r.resolved_at_utc for r in registry.rows), default=None),
            900,
            "Latest registered resolution time, not a resolution-sync heartbeat.",
        )
        if telemetry.current:
            sources.update(telemetry.current.source_health)
        cutoff = now() - timedelta(minutes=15)
        recent = [
            r
            for r in rows
            if stamp(r.processed_at_utc)
            and stamp(r.processed_at_utc) >= cutoff
            and stamp(r.processed_at_utc) <= now()
        ]
        predictions = sum(r.model_probability_yes is not None for r in recent)
        fields = (
            "btc_price",
            "strike",
            "yes_bid",
            "yes_ask",
            "no_bid",
            "no_ask",
            "reference_timestamp",
            "yes_book_timestamp",
            "no_book_timestamp",
        )
        raw_telemetry, _ = self.reader.telemetry()
        visible_times = {r.observed_at for r in telemetry.rows}
        sample = [r for r in raw_telemetry or [] if r["observed_at"] in visible_times]
        return Health(
            generated_at=now().isoformat(),
            sources=sources,
            process_status=process_status,
            recent_decisions=len(recent),
            prediction_count_15m=predictions,
            predictions_per_minute_15m=predictions / 15,
            reason_counts=dict(Counter(r.reason for r in recent)),
            missing_telemetry={
                f: sum(
                    (stamp(r.get(f)) if f.endswith("timestamp") else number(r.get(f))) is None for r in sample
                )
                for f in fields
            },
            telemetry_sample_size=len(sample),
            latest_market=telemetry.current.market_id if telemetry.current else None,
            scope="Decision rates: last 15 minutes within the bounded journal window. Telemetry nulls: displayed observation window. Runtime state comes from its heartbeat; settlement-worker liveness is unavailable.",
        )

    def performance(self):
        report, source = self.reader.report()
        if report and source.state == "ok":
            source = freshness(
                report.created_at_utc, 900, "Existing report snapshot; the dashboard does not regenerate it."
            )
        rows, _ = self.decision_rows()
        buckets = defaultdict(lambda: {"decisions": 0, "predictions": 0, "verified": 0})
        for r in rows:
            date = stamp(r.target_at_utc)
            if date:
                b = buckets[date.strftime("%Y-%m-%d %H:00 UTC")]
                b["decisions"] += 1
                b["predictions"] += r.model_probability_yes is not None
                b["verified"] += r.verified_outcome is not None
        warnings = [
            "Repeated horizons within a market are correlated. Prediction rows are not independent markets. Diagnostic results do not establish superiority, statistical significance or profitability."
        ]
        if report and report.coverage.get("resolved_model_markets", 0) < 100:
            warnings.append(
                "Insufficient independent-market sample for reliable performance conclusions (dashboard caution threshold: 100 markets)."
            )
        if not report or not report.paired_model:
            warnings.append(
                "Paired model-versus-market scores unavailable: the report has no resolved pairs with prediction-time market probabilities."
            )
        return Performance(
            report=report,
            source=source,
            portfolio=self.portfolio(),
            coverage_over_time=[{"time": k, **v} for k, v in sorted(buckets.items())],
            warnings=warnings,
        )

    def overview(self, minutes=15):
        telemetry = self.telemetry(minutes)
        current = telemetry.current
        active = self.decisions(market=current.market_id, page_size=100).rows if current else []
        latest = active[0] if active else None
        provenance = "Unknown — no independent provenance attestation is stored in the monitoring sources."
        if latest and "provenance" in latest.reason:
            provenance = latest.reason_info.explanation
        elif latest and latest.status == "SHADOW_FILLED":
            provenance = "Latest journal decision records an authorized shadow fill; this is historical evidence, not current execution authorization."
        heartbeat, _ = self.reader.runtime()
        mode = (
            "PAPER EXECUTION"
            if heartbeat and heartbeat.get("mode") == "paper_execution"
            else "SHADOW ONLY"
            if heartbeat
            else "UNKNOWN"
        )
        return Overview(
            generated_at=now().isoformat(),
            mode=mode,
            telemetry=telemetry,
            decisions=self.decisions(page_size=8),
            active_predictions=active,
            resolutions=self.resolutions().model_copy(update={"rows": self.resolutions().rows[:5]}),
            portfolio=self.portfolio(),
            health=self.health(telemetry),
            provenance=provenance,
        )
