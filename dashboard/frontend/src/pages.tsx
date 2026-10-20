import { useState } from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { RefreshCw, Search, Shield, SlidersHorizontal } from "lucide-react";
import {
  Badge,
  Book,
  DecisionTable,
  Empty,
  KeyValue,
  Metric,
  Notice,
  Panel,
  PollState,
  PortfolioPanel,
  PriceChart,
  ProbabilityChart,
  ResolutionTable,
  SourceState,
  fmt,
  horizons,
  pct,
  short,
  time,
} from "./components";
import { useClock, usePoll } from "./hooks";
import type {
  DecisionPage,
  Overview,
  Performance,
  Preferences,
  ResolutionPage,
  SettingsResponse,
} from "./types";

export function MarketOverview({
  data,
  prefs,
  detailed = false,
}: {
  data: Overview;
  prefs: Preferences;
  detailed?: boolean;
}) {
  const clock = useClock();
  const market = data.telemetry.current;
  const predictions = data.active_predictions;
  const prediction = predictions.find((r) => r.model_probability_yes != null);
  const remaining = market?.market_end_at
    ? Math.ceil((Date.parse(market.market_end_at) - clock) / 1000)
    : null;
  const active = market?.active && remaining != null && remaining > 0;
  const age = market?.observed_at
    ? (clock - Date.parse(market.observed_at)) / 1000
    : null;
  const fresh =
    data.telemetry.source.state === "ok" && age != null && age >= 0 && age <= 5;
  return (
    <>
      {!detailed && (
        <>
          <PortfolioPanel portfolio={data.portfolio} />
          <p className="runtime-summary">{data.health.process_status}</p>
        </>
      )}
      <div className="market-heading">
        <div className="market-symbol">₿</div>
        <div>
          <div className="inline">
            <h2>
              Bitcoin <span className="muted">/ USD</span>
            </h2>
            <Badge tone={active ? "cyan" : "warn"}>
              {active ? "5 MIN MARKET" : "LAST OBSERVED MARKET"}
            </Badge>
          </div>
          <p>
            {market?.question || "Waiting for collector observations"}{" "}
            {market && (
              <span className="mono" title={market.market_id}>
                {" "}
                · {short(market.market_id)}
              </span>
            )}
          </p>
        </div>
        <div className="market-clock">
          <span>{active ? "TIME TO EXPIRY" : "MARKET STATUS"}</span>
          <strong>
            {remaining == null
              ? "—"
              : remaining <= 0
                ? "Expired"
                : `${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, "0")}`}
          </strong>
        </div>
      </div>
      {!fresh && (
        <Notice>
          Telemetry{" "}
          {age != null && age < 0
            ? "is future-dated"
            : "is stale or unavailable"}
          . Values below are the last observed data.{" "}
          {age != null && `Observation age: ${fmt(age, 1)}s.`}
        </Notice>
      )}
      <div className="metrics main-metrics">
        <Metric
          label="BTC reference"
          value={market?.btc_price == null ? "—" : `$${fmt(market.btc_price)}`}
          hint="Chainlink · collected observation"
        />
        <Metric
          label="Market strike"
          value={market?.strike == null ? "—" : `$${fmt(market.strike)}`}
          hint={
            market?.distance == null
              ? "Distance unavailable"
              : `${market.distance >= 0 ? "+" : ""}$${fmt(market.distance)} from strike`
          }
        />
        <Metric
          label="HGB3 · P(YES)"
          value={pct(prediction?.model_probability_yes)}
          hint={
            prediction
              ? `${prediction.horizon_seconds}s horizon · ${time(prediction.target_at_utc, prefs.timezone)}`
              : "No prediction for this market"
          }
          tone="text-cyan"
        />
        <Metric
          label="Market · P(YES)"
          value={pct(market?.market_probability_yes)}
          hint="Latest normalized YES midpoint"
        />
        <Metric
          label="Latest decision"
          value={<Badge>{predictions[0]?.status || "PENDING"}</Badge>}
          hint={
            predictions[0]?.reason.replaceAll("_", " ") ||
            "Awaiting scheduled horizon"
          }
        />
      </div>
      <div className="grid-market">
        <Panel
          title="Reference price"
          eyebrow="LIVE MARKET TELEMETRY"
          actions={
            <div className="inline">
              <SourceState source={data.telemetry.source} />
              <Badge>{prefs.window} MIN WINDOW</Badge>
            </div>
          }
        >
          <PriceChart telemetry={data.telemetry} zone={prefs.timezone} />
        </Panel>
        <Panel title="Decision context" eyebrow="HGB3 / FROZEN MODEL">
          <div className="context-prob">
            <span>LATEST MODEL PROBABILITY</span>
            <strong>{pct(prediction?.model_probability_yes)}</strong>
            <div className="prob-track">
              <i
                style={{
                  width: `${(prediction?.model_probability_yes ?? 0) * 100}%`,
                }}
              />
            </div>
            <div className="split">
              <span>YES {pct(prediction?.model_probability_yes)}</span>
              <span>NO {pct(prediction?.model_probability_no)}</span>
            </div>
          </div>
          <div className="context-rows">
            <KeyValue label="Paired market probability">
              {pct(prediction?.prediction_market_probability_yes)}
            </KeyValue>
            <KeyValue label="Model − market">
              {prediction?.probability_difference == null
                ? "Unavailable"
                : `${fmt(prediction.probability_difference * 100, 1)} pp`}
            </KeyValue>
            <KeyValue label="Prediction horizon">
              {prediction ? `${prediction.horizon_seconds}s` : "Pending"}
            </KeyValue>
            <KeyValue label="Execution mode">
              <Badge>{data.mode}</Badge>
            </KeyValue>
          </div>
          <div className="safety-note">
            <Shield size={17} />
            <div>
              <strong>Execution provenance</strong>
              <p>{data.provenance}</p>
            </div>
          </div>
        </Panel>
      </div>
      {detailed ? (
        <>
          <div className="grid-two">
            <Book market={market} />
            <Panel
              title="Market identity & timing"
              actions={<Badge>{prefs.timezone}</Badge>}
            >
              <div className="detail-body">
                <KeyValue label="Condition ID">
                  {market?.market_id || "Unavailable"}
                </KeyValue>
                <KeyValue label="Expiry">
                  {market?.market_end_at || "Unavailable"}
                </KeyValue>
                <KeyValue label="Collector observation">
                  {market?.observed_at || "Unavailable"}
                </KeyValue>
                {(["reference", "yes_book", "no_book"] as const).map((key) => (
                  <div key={key}>
                    <KeyValue label={`${key.replaceAll("_", " ")} source time`}>
                      {market?.[`${key}_timestamp`] || "Unavailable"}
                    </KeyValue>
                    <KeyValue label="Age at collector observation">
                      {fmt(market?.[`${key}_age_ms`], 1)} ms
                    </KeyValue>
                    <KeyValue label="Current source age">
                      {fmt(market?.source_health[key]?.age_seconds, 3)} s
                    </KeyValue>
                  </div>
                ))}
              </div>
            </Panel>
          </div>
          <Panel title="Data quality">
            <div className="detail-body">
              {market?.warnings.length ? (
                market.warnings.map((w) => <Notice key={w}>{w}</Notice>)
              ) : (
                <p>No source-age warnings in the latest observation.</p>
              )}
              <p className="muted">
                {data.telemetry.scope} Source ages are preserved, including
                negative values. Runner thresholds: reference 3,000 ms; books
                500 ms.
              </p>
            </div>
          </Panel>
        </>
      ) : (
        <>
          <div className="grid-two">
            <Panel title="Model vs. market" eyebrow="SAME PREDICTION CUTOFF">
              <ProbabilityChart rows={predictions} />
              <p className="panel-description">
                Paired by horizon. Current or execution-time quotes are never
                used as the historical baseline.
              </p>
            </Panel>
            <Book market={market} />
          </div>
          <Panel
            title="Recent decisions"
            eyebrow="DECISION JOURNAL"
            actions={<Badge>LAST {data.decisions.rows.length} RECORDS</Badge>}
          >
            <DecisionTable
              rows={data.decisions.rows}
              zone={prefs.timezone}
              compact
            />
          </Panel>
          <div className="grid-two">
            <Panel
              title="Verified resolutions"
              actions={<Badge>REGISTRY EVIDENCE</Badge>}
            >
              <ResolutionTable
                rows={data.resolutions.rows}
                zone={prefs.timezone}
                compact
              />
            </Panel>
            <Panel
              title="Data quality & safety"
              actions={
                <Badge tone="warn">
                  {market?.warnings.length || 0} OBSERVATION FLAGS
                </Badge>
              }
            >
              <div className="warning-list">
                {market?.warnings.length ? (
                  market.warnings
                    .slice(0, 4)
                    .map((w) => <Notice key={w}>{w}</Notice>)
                ) : (
                  <p className="muted">
                    No observation-level warnings recorded.
                  </p>
                )}
                <p>
                  Abstention can be the correct safety outcome. Source
                  timestamps do not establish execution authorization.
                </p>
              </div>
            </Panel>
          </div>
        </>
      )}
    </>
  );
}

export function JournalPage({
  prefs,
  overview,
  predictions = false,
}: {
  prefs: Preferences;
  overview: Overview;
  predictions?: boolean;
}) {
  const [filters, setFilters] = useState({
    search: "",
    horizon: "",
    reason: "",
    status: "",
    availability: "all",
    outcome: "all",
    minimum: "",
    maximum: "",
    after: "",
    before: "",
    sort: "target_at_utc",
    direction: "desc",
    market: "",
  });
  const [page, setPage] = useState(1);
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(prefs.pageSize),
  });
  Object.entries(filters).forEach(([key, value]) => {
    if (value)
      query.set(
        key,
        key === "after" || key === "before"
          ? new Date(`${value}Z`).toISOString()
          : value,
      );
  });
  const result = usePoll<DecisionPage>(
    `/api/${predictions ? "predictions" : "decisions"}?${query}`,
    predictions ? 10000 : prefs.refresh * 1000,
  );
  const change = (key: keyof typeof filters, value: string) => {
    setFilters((old) => ({ ...old, [key]: value }));
    setPage(1);
  };
  return (
    <>
      <PollState {...result} />
      {predictions && (
        <>
          <Panel
            title="Active market · scheduled horizons"
            actions={
              <Badge>
                {overview.telemetry.current
                  ? short(overview.telemetry.current.market_id)
                  : "NO MARKET"}
              </Badge>
            }
          >
            <div className="horizon-grid">
              {horizons.map((h) => {
                const row = overview.active_predictions.find(
                  (r) => r.horizon_seconds === h,
                );
                const expiry = overview.telemetry.current?.market_end_at;
                return (
                  <div key={h}>
                    <span>T − {h}s</span>
                    <strong>{pct(row?.model_probability_yes)}</strong>
                    <small>
                      {row
                        ? row.reason.replaceAll("_", " ")
                        : "No journal record yet"}
                    </small>
                    <small>
                      {row
                        ? time(row.target_at_utc, prefs.timezone)
                        : expiry
                          ? time(
                              new Date(
                                Date.parse(expiry) - h * 1000,
                              ).toISOString(),
                              prefs.timezone,
                            )
                          : "Unknown target"}
                    </small>
                  </div>
                );
              })}
            </div>
            <ProbabilityChart rows={overview.active_predictions} />
          </Panel>
          <Notice>
            A high model probability alone does not imply a profitable trade.
            Costs, execution prices, provenance and risk gates apply.
          </Notice>
        </>
      )}
      <Panel
        title={predictions ? "Prediction history" : "Decision journal"}
        eyebrow="SEARCHABLE RECORDS"
        actions={
          <button className="button" onClick={result.refresh}>
            <RefreshCw size={13} />
            Refresh
          </button>
        }
      >
        <div className="filters">
          <label className="search-input">
            <Search size={14} />
            <input
              aria-label="Search journal"
              placeholder="Search market, status or reason…"
              value={filters.search}
              onChange={(e) => change("search", e.target.value)}
            />
          </label>
          <select
            aria-label="Horizon filter"
            value={filters.horizon}
            onChange={(e) => change("horizon", e.target.value)}
          >
            <option value="">All horizons</option>
            {horizons.map((h) => (
              <option key={h} value={h}>
                {h}s
              </option>
            ))}
          </select>
          <select
            aria-label="Reason filter"
            value={filters.reason}
            onChange={(e) => change("reason", e.target.value)}
          >
            <option value="">All reasons</option>
            {result.data?.reasons.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
          <select
            aria-label="Prediction availability"
            value={filters.availability}
            onChange={(e) => change("availability", e.target.value)}
          >
            <option value="all">Any prediction availability</option>
            <option value="available">Prediction available</option>
            <option value="missing">Prediction missing</option>
          </select>
          <button
            className="button"
            onClick={() =>
              change(
                "market",
                filters.market
                  ? ""
                  : overview.telemetry.current?.market_id || "",
              )
            }
          >
            {filters.market ? "Show all markets" : "Current market only"}
          </button>
        </div>
        <details className="advanced-filters">
          <summary>
            <SlidersHorizontal size={13} /> More filters & sorting
          </summary>
          <div className="filters">
            <label>
              From (UTC)
              <input
                aria-label="From UTC"
                type="datetime-local"
                value={filters.after}
                onChange={(e) => change("after", e.target.value)}
              />
            </label>
            <label>
              Until (UTC)
              <input
                aria-label="Until UTC"
                type="datetime-local"
                value={filters.before}
                onChange={(e) => change("before", e.target.value)}
              />
            </label>
            <label>
              Minimum P(YES)
              <input
                aria-label="Minimum probability"
                type="number"
                min="0"
                max="1"
                step="0.05"
                placeholder="0.00"
                value={filters.minimum}
                onChange={(e) => change("minimum", e.target.value)}
              />
            </label>
            <label>
              Maximum P(YES)
              <input
                aria-label="Maximum probability"
                type="number"
                min="0"
                max="1"
                step="0.05"
                placeholder="1.00"
                value={filters.maximum}
                onChange={(e) => change("maximum", e.target.value)}
              />
            </label>
            <label>
              Outcome
              <select
                value={filters.outcome}
                onChange={(e) => change("outcome", e.target.value)}
              >
                <option value="all">Any outcome</option>
                <option value="verified">Verified outcome</option>
                <option value="missing">No registered outcome</option>
              </select>
            </label>
            <label>
              Status
              <select
                value={filters.status}
                onChange={(e) => change("status", e.target.value)}
              >
                <option value="">All statuses</option>
                {[
                  "ABSTAIN",
                  "SHADOW_FILLED",
                  "EVALUATING",
                  "SKIPPED",
                  "ERROR",
                ].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
            <label>
              Sort by
              <select
                value={filters.sort}
                onChange={(e) => change("sort", e.target.value)}
              >
                {[
                  "target_at_utc",
                  "horizon_seconds",
                  "model_probability_yes",
                  "status",
                  "reason",
                ].map((s) => (
                  <option key={s} value={s}>
                    {s.replaceAll("_", " ")}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Direction
              <select
                value={filters.direction}
                onChange={(e) => change("direction", e.target.value)}
              >
                <option value="desc">Descending</option>
                <option value="asc">Ascending</option>
              </select>
            </label>
          </div>
        </details>
        {result.data ? (
          <>
            <DecisionTable rows={result.data.rows} zone={prefs.timezone} />
            <footer className="pagination">
              <span>
                {result.data.total} matching records · timestamps in{" "}
                {prefs.timezone}
              </span>
              <div className="inline">
                <button
                  className="button"
                  disabled={page === 1}
                  onClick={() => setPage((p) => p - 1)}
                >
                  Previous
                </button>
                <span>
                  Page {page} /{" "}
                  {Math.max(1, Math.ceil(result.data.total / prefs.pageSize))}
                </span>
                <button
                  className="button"
                  disabled={page * prefs.pageSize >= result.data.total}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </button>
              </div>
            </footer>
            <p className="panel-description">
              {result.data.scope}{" "}
              {result.data.source.state !== "ok" && result.data.source.detail}
            </p>
          </>
        ) : (
          <Empty>Loading journal records…</Empty>
        )}
      </Panel>
      <div className="category-legend">
        {[
          "Strategy abstention",
          "Execution authorization",
          "Telemetry unavailable",
          "Invalid causal inputs",
          "Operational failure",
        ].map((s) => (
          <Badge key={s} tone={s === "Operational failure" ? "bad" : "neutral"}>
            {s}
          </Badge>
        ))}
      </div>
    </>
  );
}

export function PerformancePage() {
  const result = usePoll<Performance>("/api/performance", 60000);
  const report = result.data?.report;
  const byHorizon = horizons.map((h) => ({
    horizon: `${h}s`,
    modelBrier: report?.by_horizon[h]?.model?.brier,
    marketBrier: report?.by_horizon[h]?.market?.brier,
    modelLog: report?.by_horizon[h]?.model?.log_loss,
    marketLog: report?.by_horizon[h]?.market?.log_loss,
  }));
  const model = report?.model_all_resolved;
  const chartStyle = { background: "var(--panel)", borderColor: "var(--line)" };
  return (
    <>
      <PollState {...result} />
      <div className="page-toolbar">
        <p>Prospective evaluation · existing report snapshot</p>
        <button className="button" onClick={result.refresh}>
          <RefreshCw size={14} />
          Read latest report
        </button>
      </div>
      {result.data?.warnings.map((w) => (
        <Notice key={w}>{w}</Notice>
      ))}
      {report ? (
        <>
          <div className="metrics main-metrics">
            <Metric
              label="Model Brier score"
              value={fmt(model?.brier, 4)}
              hint="All resolved model rows · lower is better"
            />
            <Metric
              label="Model log loss"
              value={fmt(model?.log_loss, 4)}
              hint="All resolved model rows · lower is better"
            />
            <Metric
              label="Scored prediction rows"
              value={model?.n ?? 0}
              hint="Horizons are correlated"
            />
            <Metric
              label="Independent markets"
              value={model?.unique_markets ?? 0}
              hint="Markets with scored HGB3 predictions"
            />
            <Metric
              label="Prediction coverage"
              value={
                report.coverage.journal_decisions
                  ? pct(
                      report.coverage.model_predictions_all /
                        report.coverage.journal_decisions,
                    )
                  : "—"
              }
              hint={`${report.coverage.model_predictions_all} / ${report.coverage.journal_decisions} journal decisions`}
            />
          </div>
          <Panel
            title="Paired model / market comparison"
            actions={<SourceState source={result.data?.source} />}
          >
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Same resolved predictions</th>
                    <th>Brier score</th>
                    <th>Log loss</th>
                    <th>Prediction rows</th>
                    <th>Independent markets</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    ["HGB3", report.paired_model],
                    ["Prediction-time market", report.paired_market],
                  ].map(([label, raw]) => {
                    const score = typeof raw === "object" ? raw : null;
                    return (
                      <tr key={String(label)}>
                        <td>{String(label)}</td>
                        <td>{fmt(score?.brier, 4)}</td>
                        <td>{fmt(score?.log_loss, 4)}</td>
                        <td>{score?.n ?? "—"}</td>
                        <td>{score?.unique_markets ?? "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="panel-description">
              {report.paired_model
                ? "Both rows use the same eligible predictions and registered outcomes."
                : "No eligible paired comparisons in this report. Later execution quotes cannot fill this gap."}
            </p>
          </Panel>
          <div className="grid-two">
            {(["Brier score", "Log loss"] as const).map((title, index) => (
              <Panel
                key={title}
                title={`${title} by horizon`}
                actions={<Badge>UNPAIRED DIAGNOSTICS</Badge>}
              >
                <div className="chart-legend">
                  <span>
                    <i className="dot cyan" />
                    HGB3
                  </span>
                  <span>
                    <i className="dot amber" />
                    Market
                  </span>
                </div>
                <div className="small-chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={byHorizon}>
                      <CartesianGrid stroke="var(--line)" vertical={false} />
                      <XAxis
                        dataKey="horizon"
                        tick={{ fill: "var(--muted)", fontSize: 11 }}
                      />
                      <YAxis
                        tick={{ fill: "var(--muted)", fontSize: 11 }}
                        width={45}
                      />
                      <Tooltip contentStyle={chartStyle} />
                      <Bar
                        dataKey={index ? "modelLog" : "modelBrier"}
                        name="HGB3"
                        fill="#52cbd8"
                        maxBarSize={20}
                        isAnimationActive={false}
                      />
                      <Bar
                        dataKey={index ? "marketLog" : "marketBrier"}
                        name="Market"
                        fill="#c6a66b"
                        maxBarSize={20}
                        isAnimationActive={false}
                      />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              </Panel>
            ))}
          </div>
          <div className="grid-two">
            <Panel
              title="HGB3 calibration"
              actions={<Badge>RESOLVED PREDICTIONS</Badge>}
            >
              {report.calibration_model.length ? (
                <div className="small-chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart
                      data={report.calibration_model}
                      margin={{ right: 20, top: 15 }}
                    >
                      <CartesianGrid stroke="var(--line)" />
                      <XAxis
                        type="number"
                        dataKey="avg_probability"
                        domain={[0, 1]}
                        tickFormatter={pct}
                        tick={{ fill: "var(--muted)", fontSize: 11 }}
                      />
                      <YAxis
                        type="number"
                        domain={[0, 1]}
                        tickFormatter={pct}
                        tick={{ fill: "var(--muted)", fontSize: 11 }}
                        width={50}
                      />
                      <Tooltip contentStyle={chartStyle} />
                      <ReferenceLine
                        segment={[
                          { x: 0, y: 0 },
                          { x: 1, y: 1 },
                        ]}
                        stroke="#65758b"
                        strokeDasharray="4 4"
                      />
                      <Scatter
                        dataKey="yes_frequency"
                        name="Observed YES frequency"
                        fill="#52cbd8"
                        isAnimationActive={false}
                      />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <Empty>No scored calibration bins.</Empty>
              )}
              <p className="panel-description">
                X: average predicted YES · Y: observed YES frequency. Each point
                is an occupied probability bin.
              </p>
            </Panel>
            <Panel
              title="Coverage over time"
              actions={<Badge>BOUNDED JOURNAL WINDOW</Badge>}
            >
              <div className="chart-legend">
                <span>
                  <i className="dot cyan" />
                  Predictions
                </span>
                <span>
                  <i className="dot amber" />
                  Verified outcome rows
                </span>
              </div>
              <div className="small-chart">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={result.data?.coverage_over_time}>
                    <CartesianGrid stroke="var(--line)" vertical={false} />
                    <XAxis
                      dataKey="time"
                      tickFormatter={(s) => String(s).slice(11, 16)}
                      tick={{ fill: "var(--muted)", fontSize: 11 }}
                    />
                    <YAxis
                      tick={{ fill: "var(--muted)", fontSize: 11 }}
                      width={45}
                    />
                    <Tooltip contentStyle={chartStyle} />
                    <Line
                      dataKey="predictions"
                      stroke="#52cbd8"
                      isAnimationActive={false}
                    />
                    <Line
                      dataKey="verified"
                      stroke="#c6a66b"
                      isAnimationActive={false}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </Panel>
          </div>
          <Panel title="Coverage & report provenance">
            <div className="detail-grid padded">
              <KeyValue label="Report created (UTC)">
                {report.created_at_utc}
              </KeyValue>
              <KeyValue label="Verified outcome coverage">
                {report.coverage.journal_decisions
                  ? pct(
                      report.coverage.resolved_decisions /
                        report.coverage.journal_decisions,
                    )
                  : "—"}{" "}
                of journal rows
              </KeyValue>
              <KeyValue label="Verified resolution markets">
                {report.coverage.verified_resolution_markets}
              </KeyValue>
              <KeyValue label="Journal independent markets">
                {report.coverage.journal_unique_markets}
              </KeyValue>
              <KeyValue label="Market baseline Brier (all resolved)">
                {fmt(report.market_all_resolved?.brier, 4)}
              </KeyValue>
              <KeyValue label="Market baseline log loss (all resolved)">
                {fmt(report.market_all_resolved?.log_loss, 4)}
              </KeyValue>
            </div>
            <p className="panel-description">
              {result.data?.source.detail} Report state:{" "}
              {result.data?.source.state}. Report values and live journal
              coverage have different as-of times.
            </p>
          </Panel>
        </>
      ) : (
        <Empty>
          Performance report unavailable. The dashboard reads the existing v2
          report and does not run model evaluation or synthesize scores.
        </Empty>
      )}
      {result.data && <PortfolioPanel portfolio={result.data.portfolio} />}
    </>
  );
}

export function ResolutionsPage({ prefs }: { prefs: Preferences }) {
  const result = usePoll<ResolutionPage>("/api/resolutions", 15000);
  const [search, setSearch] = useState("");
  const [outcome, setOutcome] = useState("all");
  const rows =
    result.data?.rows.filter(
      (r) =>
        r.condition_id.toLowerCase().includes(search.toLowerCase()) &&
        (outcome === "all" || r.label_yes === Number(outcome)),
    ) || [];
  return (
    <>
      <PollState {...result} />
      <Notice>
        Outcomes come only from independently verified registry records. A
        verified resolution does not imply a hypothetical position was filled or
        settled.
      </Notice>
      <Panel
        title="Resolution registry"
        actions={<SourceState source={result.data?.source} />}
      >
        <div className="filters">
          <label className="search-input">
            <Search size={14} />
            <input
              aria-label="Search condition ID"
              placeholder="Search condition ID…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <select
            aria-label="Winning outcome"
            value={outcome}
            onChange={(e) => setOutcome(e.target.value)}
          >
            <option value="all">All outcomes</option>
            <option value="1">YES</option>
            <option value="0">NO</option>
          </select>
          <Badge>{rows.length} REGISTERED MARKETS</Badge>
        </div>
        <ResolutionTable rows={rows} zone={prefs.timezone} />
        <p className="panel-description">
          {result.data?.scope}{" "}
          {result.data?.source.state !== "ok" && result.data?.source.detail}
        </p>
      </Panel>
    </>
  );
}

export function HealthPage({
  overview,
  prefs,
}: {
  overview: Overview;
  prefs: Preferences;
}) {
  const health = overview.health;
  return (
    <>
      <Notice>{health.process_status}</Notice>
      <div className="metrics">
        <Metric
          label="Predictions / minute"
          value={fmt(health.predictions_per_minute_15m, 2)}
          hint="Trailing 15-minute window"
        />
        <Metric
          label="Produced predictions"
          value={health.prediction_count_15m}
          hint="Trailing 15-minute window"
        />
        <Metric
          label="Decision observations"
          value={health.recent_decisions}
          hint="Trailing 15-minute window"
        />
        <Metric
          label="Telemetry sample"
          value={health.telemetry_sample_size}
          hint="Actual bounded CSV observations"
        />
      </div>
      <Panel title="Source health" actions={<Badge>OBSERVED ACTIVITY</Badge>}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Source</th>
                <th>State</th>
                <th>Latest timestamp</th>
                <th>Age</th>
                <th>Interpretation</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(health.sources).map(([key, source]) => (
                <tr key={key}>
                  <td>{key.replaceAll("_", " ")}</td>
                  <td>
                    <SourceState source={source} />
                  </td>
                  <td>{time(source.timestamp, prefs.timezone, true)}</td>
                  <td>
                    {source.age_seconds == null
                      ? "—"
                      : `${fmt(source.age_seconds, 2)}s`}
                  </td>
                  <td className="wrap">{source.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <div className="grid-two">
        <Panel title="Decision reasons · trailing 15 minutes">
          <div className="reason-bars">
            {Object.entries(health.reason_counts).map(([key, value]) => (
              <div key={key}>
                <div className="split">
                  <span>{key.replaceAll("_", " ")}</span>
                  <b>
                    {value}{" "}
                    <small>
                      (
                      {pct(
                        health.recent_decisions
                          ? value / health.recent_decisions
                          : null,
                      )}
                      )
                    </small>
                  </b>
                </div>
                <div className="bar-track">
                  <i
                    style={{
                      width: `${health.recent_decisions ? (value / health.recent_decisions) * 100 : 0}%`,
                    }}
                  />
                </div>
              </div>
            ))}
            {!health.recent_decisions && (
              <Empty>No recent journal records.</Empty>
            )}
          </div>
        </Panel>
        <Panel title="Missing telemetry fields">
          <div className="detail-body">
            {Object.entries(health.missing_telemetry).map(([key, value]) => (
              <KeyValue key={key} label={key.replaceAll("_", " ")}>
                {value} / {health.telemetry_sample_size} (
                {pct(
                  health.telemetry_sample_size
                    ? value / health.telemetry_sample_size
                    : null,
                )}
                )
              </KeyValue>
            ))}
          </div>
        </Panel>
      </div>
      <p className="muted">{health.scope}</p>
    </>
  );
}

export function SettingsPage({
  prefs,
  setPrefs,
}: {
  prefs: Preferences;
  setPrefs: (p: Preferences) => void;
}) {
  const result = usePoll<SettingsResponse>("/api/settings", 60000);
  function change<K extends keyof Preferences>(key: K, value: Preferences[K]) {
    setPrefs({ ...prefs, [key]: value });
  }
  return (
    <>
      <Panel title="Dashboard preferences" eyebrow="SAVED IN THIS BROWSER">
        <div className="settings-grid">
          <label>
            Live refresh
            <select
              value={prefs.refresh}
              onChange={(e) => change("refresh", Number(e.target.value))}
            >
              {[1, 2, 5, 10].map((n) => (
                <option value={n} key={n}>
                  {n} seconds
                </option>
              ))}
            </select>
          </label>
          <label>
            Table page size
            <select
              value={prefs.pageSize}
              onChange={(e) => change("pageSize", Number(e.target.value))}
            >
              {[10, 25, 50, 100].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
          <label>
            Chart time window
            <select
              value={prefs.window}
              onChange={(e) => change("window", Number(e.target.value))}
            >
              {[5, 15, 30, 60].map((n) => (
                <option key={n} value={n}>
                  {n} minutes
                </option>
              ))}
            </select>
          </label>
          <label>
            Timestamp display
            <select
              value={prefs.timezone}
              onChange={(e) => change("timezone", e.target.value)}
            >
              <option>UTC</option>
              <option value="local">Local timezone</option>
              <option>Asia/Jerusalem</option>
            </select>
          </label>
          <label>
            Visual density
            <select
              value={prefs.density}
              onChange={(e) => change("density", e.target.value)}
            >
              <option value="compact">Compact</option>
              <option value="comfortable">Comfortable</option>
            </select>
          </label>
          <label>
            Theme
            <select
              value={prefs.theme}
              onChange={(e) => change("theme", e.target.value)}
            >
              <option value="dark">Terminal dark</option>
              <option value="light">Light</option>
            </select>
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={prefs.animations}
              onChange={(e) => change("animations", e.target.checked)}
            />
            Enable subtle motion (respects system reduced-motion)
          </label>
        </div>
      </Panel>
      <Panel title="Local data sources" eyebrow="STARTUP CONFIGURATION">
        <div className="detail-body">
          {Object.entries(result.data?.paths || {}).map(([key, value]) => (
            <KeyValue key={key} label={key}>
              {value}
            </KeyValue>
          ))}
          <p className="muted">
            {result.data?.path_editing || "Loading configured data paths…"}
          </p>
        </div>
      </Panel>
      <Panel
        title="Operational controls"
        actions={<Badge>NOT IMPLEMENTED</Badge>}
      >
        <div className="detail-body">
          <p>{result.data?.operational_controls}</p>
          <div className="inline">
            {[
              "Start bot",
              "Stop bot",
              "Kill switch",
              "Trading settings",
              "Risk configuration",
            ].map((label) => (
              <button disabled className="button" key={label}>
                {label}
              </button>
            ))}
          </div>
          <p className="muted">
            Dashboard preferences never modify trading configuration, model
            artifacts, collector cadence or source records.
          </p>
        </div>
      </Panel>
    </>
  );
}
