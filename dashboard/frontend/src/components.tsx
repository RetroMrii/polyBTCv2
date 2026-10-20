import { Fragment, type ReactNode, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ChevronDown,
  ChevronRight,
  CircleHelp,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import type {
  Decision,
  Market,
  Portfolio,
  Resolution,
  Source,
  Telemetry,
} from "./types";

export const horizons = [240, 180, 120, 90, 60, 30];
export const fmt = (value: number | null | undefined, digits = 2) =>
  value == null
    ? "ג€”"
    : value.toLocaleString("en-US", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });
export const pct = (value: number | null | undefined) =>
  value == null ? "ג€”" : `${fmt(value * 100, 1)}%`;
export const short = (id: string) => `${id.slice(0, 8)}ג€¦${id.slice(-6)}`;
export function time(
  value: string | null | undefined,
  zone = "UTC",
  full = false,
) {
  if (!value || !Number.isFinite(Date.parse(value))) return "Unavailable";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: zone === "local" ? undefined : zone,
    ...(full ? { month: "short", day: "2-digit" } : {}),
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}
export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
export function SourceState({
  source,
  label,
}: {
  source?: Source;
  label?: string;
}) {
  return (
    <span
      title={source?.detail}
      className={`source ${source?.state === "ok" ? "good" : "warn"}`}
    >
      <i />
      {label && `${label} ֲ· `}
      {source?.state === "ok" ? "Recent" : source?.state || "Pending"}
    </span>
  );
}
export function Panel({
  title,
  eyebrow,
  actions,
  children,
  className = "",
}: {
  title: string;
  eyebrow?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <header className="panel-head">
        <div>
          {eyebrow && <span className="eyebrow">{eyebrow}</span>}
          <h2>{title}</h2>
        </div>
        {actions}
      </header>
      {children}
    </section>
  );
}
export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="empty">
      <CircleHelp size={20} />
      <p>{children}</p>
    </div>
  );
}
export function Notice({
  children,
  critical = false,
}: {
  children: ReactNode;
  critical?: boolean;
}) {
  return (
    <div className={`notice ${critical ? "critical" : ""}`} role="status">
      <TriangleAlert size={15} />
      <span>{children}</span>
    </div>
  );
}
export function Metric({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: string;
}) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={tone}>{value}</strong>
      {hint && <small>{hint}</small>}
    </div>
  );
}
export function KeyValue({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="keyvalue">
      <span>{label}</span>
      <b>{children}</b>
    </div>
  );
}
export function PollState({
  error,
  lastSuccess,
}: {
  error?: string;
  lastSuccess?: Date;
}) {
  return error ? (
    <Notice critical>
      Backend disconnected ג€” {error}.{" "}
      {lastSuccess
        ? `Retaining data from ${lastSuccess.toISOString()}; all displayed values may be stale.`
        : "Waiting for the first successful response."}
    </Notice>
  ) : null;
}

export function PriceChart({
  telemetry,
  zone,
}: {
  telemetry: Telemetry;
  zone: string;
}) {
  const current = telemetry.current;
  const rows = telemetry.rows
    .filter((r) => r.market_id === current?.market_id)
    .map((r) => ({
      timestamp: Date.parse(r.observed_at!),
      price: r.btc_price,
    }));
  const chartRows = rows.flatMap((row, index) =>
    index && row.timestamp - rows[index - 1].timestamp > 5000
      ? [{ timestamp: rows[index - 1].timestamp + 1, price: null }, row]
      : [row],
  );
  const end = current?.market_end_at
    ? Date.parse(current.market_end_at)
    : undefined;
  const values = rows.flatMap((r) => (r.price == null ? [] : [r.price]));
  if (current?.strike != null) values.push(current.strike);
  const low = Math.min(...values),
    high = Math.max(...values),
    pad = Math.max((high - low) * 0.15, 2);
  return (
    <>
      <div className="chart-legend">
        <span>
          <i className="dot cyan" />
          Chainlink BTC/USD
        </span>
        <span>
          <i className="dash" />
          Market strike
        </span>
        <span className="muted">Vertical guides: scheduled horizons</span>
      </div>
      {rows.length && values.length ? (
        <div className="price-chart">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              data={chartRows}
              margin={{ top: 15, right: 16, left: 8, bottom: 0 }}
            >
              <defs>
                <linearGradient id="priceFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#42c7d9" stopOpacity={0.16} />
                  <stop offset="100%" stopColor="#42c7d9" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid
                vertical={false}
                stroke="var(--line)"
                strokeDasharray="3 5"
              />
              <XAxis
                dataKey="timestamp"
                type="number"
                domain={["dataMin", end || "dataMax"]}
                tickFormatter={(v) =>
                  time(new Date(v).toISOString(), zone).slice(0, 5)
                }
                tick={{ fill: "var(--muted)", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                minTickGap={35}
              />
              <YAxis
                domain={[low - pad, high + pad]}
                orientation="right"
                tickFormatter={(v) => fmt(v, 0)}
                tick={{ fill: "var(--muted)", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={65}
              />
              <Tooltip
                labelFormatter={(v) =>
                  time(new Date(Number(v)).toISOString(), zone, true)
                }
                contentStyle={{
                  background: "var(--panel)",
                  border: "1px solid var(--line)",
                  borderRadius: 5,
                }}
                formatter={(v) => [`$${fmt(Number(v))}`, "BTC reference"]}
              />
              {current?.strike != null && (
                <ReferenceLine
                  y={current.strike}
                  stroke="#b9a475"
                  strokeDasharray="5 5"
                />
              )}
              {end &&
                horizons.map((h) => (
                  <ReferenceLine
                    key={h}
                    x={end - h * 1000}
                    stroke="var(--line)"
                    strokeDasharray="2 5"
                    label={{
                      value: `${h}s`,
                      position: "insideTopLeft",
                      fill: "var(--muted)",
                      fontSize: 10,
                    }}
                  />
                ))}
              <Area
                dataKey="price"
                stroke="#52cbd8"
                strokeWidth={1.8}
                fill="url(#priceFill)"
                isAnimationActive={false}
                connectNulls={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <Empty>
          No price observations for the selected market in this chart window.
        </Empty>
      )}
      <footer className="panel-foot">
        <span>
          {rows.length} collected observations ֲ·{" "}
          {rows.length
            ? `${time(new Date(rows[0].timestamp).toISOString(), zone)} ג€” ${time(new Date(rows[rows.length - 1].timestamp).toISOString(), zone)}`
            : "No available window"}
        </span>
        <span>{zone}</span>
      </footer>
    </>
  );
}

export function ProbabilityChart({ rows }: { rows: Decision[] }) {
  const data = horizons.map((h) => {
    const r = rows.find((row) => row.horizon_seconds === h);
    return {
      horizon: `${h}s`,
      HGB3: r?.model_probability_yes ?? null,
      Market: r?.prediction_market_probability_yes ?? null,
    };
  });
  if (!data.some((r) => r.HGB3 != null || r.Market != null))
    return (
      <Empty>
        No prediction-time probabilities recorded for this market yet.
      </Empty>
    );
  return (
    <>
      <div className="chart-legend">
        <span>
          <i className="dot cyan" />
          HGB3 YES
        </span>
        <span>
          <i className="dot amber" />
          Market YES at prediction
        </span>
      </div>
      <div className="small-chart">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ right: 24, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--line)" />
            <XAxis
              dataKey="horizon"
              tick={{ fill: "var(--muted)", fontSize: 11 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              domain={[0, 1]}
              tickFormatter={pct}
              tick={{ fill: "var(--muted)", fontSize: 11 }}
              width={48}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              contentStyle={{
                background: "var(--panel)",
                borderColor: "var(--line)",
              }}
              formatter={(v) => pct(Number(v))}
            />
            <Line
              dataKey="HGB3"
              stroke="#52cbd8"
              strokeWidth={2}
              dot={{ r: 3 }}
              isAnimationActive={false}
            />
            <Line
              dataKey="Market"
              stroke="#c6a66b"
              strokeWidth={1.5}
              strokeDasharray="4 4"
              dot={{ r: 3 }}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}

export function DecisionTable({
  rows,
  zone,
  compact = false,
}: {
  rows: Decision[];
  zone: string;
  compact?: boolean;
}) {
  const [open, setOpen] = useState<number | null>(null);
  if (!rows.length)
    return (
      <Empty>
        No journal records match this view. No predictions or decisions have
        been substituted.
      </Empty>
    );
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th aria-label="Details" />
            <th>Market / target</th>
            <th>Horizon</th>
            <th>Status</th>
            <th>HGB3 YES</th>
            <th>Market @ prediction</th>
            {!compact && (
              <>
                <th>HGB3 NO</th>
                <th>־” model / market</th>
                <th>Market @ execution</th>
                <th>Fill price</th>
              </>
            )}
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <Fragment key={r.id}>
              <tr className={open === r.id ? "selected" : ""}>
                <td>
                  <button
                    className="icon-button"
                    aria-label={`Details for decision ${r.id}`}
                    aria-expanded={open === r.id}
                    onClick={() => setOpen(open === r.id ? null : r.id)}
                  >
                    {open === r.id ? (
                      <ChevronDown size={14} />
                    ) : (
                      <ChevronRight size={14} />
                    )}
                  </button>
                </td>
                <td title={r.condition_id}>
                  <span className="mono">{short(r.condition_id)}</span>
                  <small>{time(r.target_at_utc, zone, true)}</small>
                </td>
                <td className="mono">{r.horizon_seconds}s</td>
                <td>
                  <Badge
                    tone={
                      r.status === "SHADOW_FILLED"
                        ? "good"
                        : r.reason_info.category === "Operational failure"
                          ? "bad"
                          : "neutral"
                    }
                  >
                    {r.status}
                  </Badge>
                </td>
                <td className="mono bright">{pct(r.model_probability_yes)}</td>
                <td className="mono">
                  {pct(r.prediction_market_probability_yes)}
                </td>
                {!compact && (
                  <>
                    <td>{pct(r.model_probability_no)}</td>
                    <td>
                      {r.probability_difference == null
                        ? "ג€”"
                        : `${fmt(r.probability_difference * 100, 1)} pp`}
                    </td>
                    <td>{pct(r.market_probability_yes)}</td>
                    <td>{fmt(r.execution_price, 3)}</td>
                  </>
                )}
                <td>
                  <span className="reason-code">
                    {r.reason.replaceAll("_", " ")}
                  </span>
                  <small>{r.reason_info.category}</small>
                </td>
              </tr>
              {open === r.id && (
                <tr className="detail">
                  <td colSpan={compact ? 7 : 11}>
                    <div className="detail-body">
                      <p>
                        <ShieldCheck size={15} />
                        {r.reason_info.explanation}
                      </p>
                      <div className="detail-grid">
                        <KeyValue label="Exact reason code">
                          {r.reason}
                        </KeyValue>
                        <KeyValue label="Condition ID">
                          {r.condition_id}
                        </KeyValue>
                        <KeyValue label="Prediction target">
                          {r.target_at_utc}
                        </KeyValue>
                        <KeyValue label="Snapshot observed">
                          {r.snapshot_observed_at_utc || "Unavailable"}
                        </KeyValue>
                        <KeyValue label="Snapshot ingested">
                          {r.snapshot_ingested_at_utc || "Unavailable"}
                        </KeyValue>
                        <KeyValue label="Snapshot ID">
                          {r.snapshot_id || "No eligible snapshot"}
                        </KeyValue>
                        <KeyValue label="Processed">
                          {r.processed_at_utc}
                        </KeyValue>
                        <KeyValue label="Verified outcome">
                          {r.verified_outcome == null
                            ? r.outcome_state
                            : `${r.verified_outcome ? "YES" : "NO"} ֲ· ${r.outcome_state}`}
                        </KeyValue>
                      </div>
                      {r.validation_warnings.map((w) => (
                        <Notice key={w}>{w}</Notice>
                      ))}
                      {r.prediction_market_probability_yes == null && (
                        <p className="muted">
                          Prediction-time market probability was not recorded.
                          Execution-time quotes are never substituted.
                        </p>
                      )}
                    </div>
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ResolutionTable({
  rows,
  zone,
  compact = false,
}: {
  rows: Resolution[];
  zone: string;
  compact?: boolean;
}) {
  return rows.length ? (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Condition ID</th>
            <th>Outcome</th>
            <th>Resolved</th>
            <th>Registry</th>
            {!compact && (
              <>
                <th>Evidence</th>
                <th>Settlement</th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.condition_id}>
              <td title={r.condition_id} className="mono">
                {short(r.condition_id)}
              </td>
              <td>
                <Badge tone={r.label_yes ? "cyan" : "neutral"}>
                  {r.label_yes ? "YES" : "NO"}
                </Badge>
              </td>
              <td>{time(r.resolved_at_utc, zone, true)}</td>
              <td>
                <span className="verified">
                  <ShieldCheck size={12} />
                  {r.settlement_status}
                </span>
              </td>
              {!compact && (
                <>
                  <td>
                    <details>
                      <summary>{r.evidence_source}</summary>
                      <p className="break mono">
                        Validation ID: {r.evidence_id}
                      </p>
                      <p className="break mono">Condition: {r.condition_id}</p>
                    </details>
                  </td>
                  <td>
                    {r.settlement_status === "SETTLED"
                      ? time(r.settled_at_utc, zone, true)
                      : "No settled trade recorded"}
                  </td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <Empty>No verified outcomes available in the registry.</Empty>
  );
}

export function PortfolioPanel({ portfolio }: { portfolio: Portfolio }) {
  const money = (value: number | null) =>
    value == null ? "—" : `${value < 0 ? "−" : ""}$${fmt(Math.abs(value))}`;
  const positions = portfolio.entries.slice(0, 20);
  return (
    <section className="portfolio-focus" aria-label="Paper trading performance">
      <Panel
        title="Paper performance"
        eyebrow="SIMULATED ACCOUNTING · CURRENT RUN"
        actions={<SourceState source={portfolio.source} />}
      >
        <div className="pnl-summary">
          <div className="pnl-hero">
            <span>NET REALIZED P&amp;L</span>
            <strong
              className={
                portfolio.realized_pnl != null && portfolio.realized_pnl < 0
                  ? "text-loss"
                  : "text-cyan"
              }
            >
              {money(portfolio.realized_pnl)}
            </strong>
            <p>After simulated entry fees · settled positions only</p>
          </div>
          <div className="metrics pnl-metrics">
            <Metric
              label="Capital at risk"
              value={money(portfolio.exposure)}
              hint="Open cost + pending reservations"
            />
            <Metric
              label="Reserved capital"
              value={money(portfolio.reserved)}
              hint={`${portfolio.pending ?? "—"} pending entries`}
            />
            <Metric
              label="Win rate"
              value={pct(portfolio.win_rate)}
              hint={`${portfolio.settled ?? "—"} settled positions`}
            />
            <Metric
              label="Open positions"
              value={portfolio.filled ?? "—"}
              hint={`${portfolio.total_fills ?? "—"} total fills`}
            />
            <Metric
              label="Entry fees"
              value={money(portfolio.fees)}
              hint="All audited fills · simulated"
            />
          </div>
        </div>
        <p className="panel-description">{portfolio.detail}</p>
      </Panel>
      <div className="grid-two">
        <Panel
          title="Cumulative realized P&L"
          eyebrow="SETTLEMENT HISTORY · USD"
        >
          {portfolio.pnl_history.length ? (
            <div className="pnl-chart">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart
                  data={portfolio.pnl_history}
                  margin={{ top: 20, right: 20, bottom: 10, left: 0 }}
                >
                  <CartesianGrid stroke="var(--line)" vertical={false} />
                  <XAxis
                    dataKey="time"
                    tickFormatter={(v: string) => time(v, "UTC")}
                    minTickGap={45}
                    tick={{ fill: "var(--muted)", fontSize: 10 }}
                  />
                  <YAxis
                    tickFormatter={(v: number) => `$${fmt(v)}`}
                    width={65}
                    tick={{ fill: "var(--muted)", fontSize: 10 }}
                  />
                  <Tooltip
                    labelFormatter={(v) => `${String(v)} · UTC`}
                    formatter={(v) => [money(Number(v)), "Realized P&L"]}
                    contentStyle={{
                      background: "var(--panel)",
                      borderColor: "var(--line)",
                    }}
                  />
                  <ReferenceLine
                    y={0}
                    stroke="var(--muted)"
                    strokeDasharray="4 4"
                  />
                  <Line
                    type="stepAfter"
                    dataKey="pnl"
                    stroke="var(--cyan)"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    isAnimationActive={false}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <Empty>
              <strong>
                {portfolio.realized_pnl == null
                  ? "P&L history unavailable"
                  : "Waiting for the first settlement"}
              </strong>
              <p>
                The curve records audited realized results. Open positions are
                not marked to market.
              </p>
            </Empty>
          )}
        </Panel>
        <Panel
          title="Positions & recent trades"
          eyebrow="LATEST 20 LEDGER ENTRIES"
        >
          {positions.length ? (
            <div className="table-wrap position-table">
              <table>
                <thead>
                  <tr>
                    <th>Market / side</th>
                    <th>Status</th>
                    <th>Shares / price</th>
                    <th>Realized</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((entry) => (
                    <tr key={String(entry.id)}>
                      <td title={String(entry.condition_id)}>
                        <span className="mono">
                          {short(String(entry.condition_id))}
                        </span>
                        <small>{String(entry.side ?? "—")}</small>
                      </td>
                      <td>
                        <Badge>{String(entry.status)}</Badge>
                      </td>
                      <td className="mono">
                        {typeof entry.filled_size === "number"
                          ? fmt(entry.filled_size, 0)
                          : "—"}
                        <small>
                          {typeof entry.execution_price === "number"
                            ? money(entry.execution_price)
                            : "—"}
                        </small>
                      </td>
                      <td className="mono">
                        {entry.status === "SETTLED" &&
                        portfolio.realized_pnl != null &&
                        typeof entry.realized_pnl === "number"
                          ? money(entry.realized_pnl)
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty>
              <strong>No positions yet</strong>
              <p>
                Paper fills will appear here when the strategy and verification
                gates authorize an entry.
              </p>
            </Empty>
          )}
        </Panel>
      </div>
    </section>
  );
}

export function Book({ market }: { market: Market | null }) {
  return (
    <Panel title="Top of book" actions={<Badge>OBSERVED QUOTES</Badge>}>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Outcome</th>
              <th>Bid / size</th>
              <th>Ask / size</th>
              <th>Spread</th>
            </tr>
          </thead>
          <tbody>
            {(["yes", "no"] as const).map((side) => (
              <tr key={side}>
                <td>
                  <Badge tone={side === "yes" ? "cyan" : "neutral"}>
                    {side.toUpperCase()}
                  </Badge>
                </td>
                <td className="mono">
                  {fmt(market?.[`${side}_bid`], 3)}
                  <small>{fmt(market?.[`${side}_bid_size`], 1)} shares</small>
                </td>
                <td className="mono">
                  {fmt(market?.[`${side}_ask`], 3)}
                  <small>{fmt(market?.[`${side}_ask_size`], 1)} shares</small>
                </td>
                <td className="mono">{fmt(market?.[`${side}_spread`], 3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
