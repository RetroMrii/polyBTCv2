import { useEffect, useMemo, useState } from "react";
import {
  ArrowUpRight,
  ArrowRight,
  ArrowLeft,
  BookOpen,
  Download,
  Moon,
  Sun,
  Search,
  ExternalLink,
} from "lucide-react";
import {
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from "recharts";
import papers from "./generated/papers.json";
import snapshot from "./generated/demo.json";
import forecast from "./generated/forecast.json";
import { LocalMonitor } from "./local-monitor";
import "./research.css";

const localPages = [
  "Overview",
  "Live Market",
  "Predictions",
  "Decisions",
  "Performance",
  "Resolutions",
  "System Health",
  "Settings",
];
const localEnabled =
  import.meta.env.DEV || import.meta.env.VITE_ENABLE_LOCAL_MONITOR === "true";
const github = (import.meta.env.VITE_GITHUB_URL as string | undefined) || "https://github.com/RetroMrii/polyBTCv2";
const sourceNames = [
  [
    "data-evidence",
    "Data provenance",
    "Schema, coverage, normalization rules and source membership.",
  ],
  [
    "model-evidence",
    "Historical models",
    "Matched walk-forward scores, model and feature comparisons.",
  ],
  [
    "forecast-evidence",
    "Calibration and forecasts",
    "Cohorts, proper scores, reliability bins and paired intervals.",
  ],
  [
    "timing-evidence",
    "Execution timing",
    "Observed funnel, timing distributions and counterfactual limits.",
  ],
  [
    "economics-evidence",
    "Strategy economics",
    "Controlled policies, sensitivity results and accounting checks.",
  ],
];
const fmt = (v: number) => v.toFixed(4);
const date = (v: string) =>
  new Date(v).toISOString().slice(0, 19).replace("T", " ");
type Row = (typeof snapshot.rows)[number];
type Model = "raw" | "platt" | "isotonic" | "combination";
const modelNames: Record<Model, string> = {
  raw: "Raw HGB3",
  platt: "Platt HGB3",
  isotonic: "Isotonic HGB3",
  combination: "Market / Platt blend",
};

function score(rows: Row[], key: Model | "market") {
  const counts = new Map<string, number>();
  for (const row of rows)
    counts.set(row.market_id, (counts.get(row.market_id) || 0) + 1);
  let brier = 0,
    logLoss = 0;
  for (const row of rows) {
    const weight = 1 / counts.get(row.market_id)! / counts.size;
    const p = Math.max(1e-15, Math.min(1 - 1e-15, row[key]));
    brier += weight * (row[key] - row.y) ** 2;
    logLoss -= weight * (row.y * Math.log(p) + (1 - row.y) * Math.log1p(-p));
  }
  return { brier, logLoss, markets: counts.size };
}

function PaperList() {
  return (
    <div className="publication-list">
      {papers.map((paper, i) => (
        <a
          className="publication-row"
          key={paper.slug}
          href={`#/papers/${paper.slug}`}
        >
          <span className="paper-index">{String(i + 1).padStart(2, "0")}</span>
          <div>
            <span className="research-kicker">{paper.category}</span>
            <h3>{paper.title}</h3>
            <p>{paper.summary}</p>
          </div>
          <span className="paper-time">
            {paper.reading_minutes} min <ArrowUpRight size={20} />
          </span>
        </a>
      ))}
    </div>
  );
}

function Home() {
  return (
    <>
      <section className="research-hero">
        <div className="hero-copy">
          <p className="research-kicker">
            Machine learning · Prediction markets · Systems
          </p>
          <h1>
            Can machine learning
            <br />
            find an edge?
          </h1>
          <p className="hero-question">
            An engineering investigation into Polymarket’s five-minute Bitcoin
            markets.
          </p>
          <p className="hero-detail">
            We tested whether models improve on market-implied probabilities—and
            whether any advantage survives the costs and constraints of
            execution.
          </p>
          <a className="research-button" href="#/papers">
            Read the research <ArrowRight size={17} />
          </a>
        </div>
        <aside className="hero-finding">
          <span className="research-kicker">The central finding</span>
          <h2>
            No demonstrated
            <br />
            incremental edge.
          </h2>
          <p>
            Market probabilities beat the frozen model on point estimates. The
            small paired sample leaves material uncertainty.
          </p>
          <div className="finding-comparison">
            <div>
              <span>Market midpoint</span>
              <b>0.1232</b>
              <i style={{ width: "61.6%" }} />
            </div>
            <div>
              <span>Raw HGB3</span>
              <b>0.1506</b>
              <i className="model-bar" style={{ width: "75.3%" }} />
            </div>
          </div>
          <p className="research-caption">
            Brier loss · lower is better
            <br />
            93 later observations / 55 markets · October 13, 2026
          </p>
          <a className="text-link" href="#/papers/forecast-calibration">
            Read the result and its limits <ArrowUpRight size={16} />
          </a>
        </aside>
      </section>
      <section className="collection-section">
        <div className="section-heading">
          <div>
            <span className="research-kicker">The publication collection</span>
            <h2>Five questions. One investigation.</h2>
          </div>
          <p>
            From raw evidence to forecasts, timing and economic reality. Each
            paper links to methods, limitations and reproducible results.
          </p>
        </div>
        <PaperList />
      </section>
      <section className="engine-invitation">
        <div>
          <span className="research-kicker">Explore the evidence</span>
          <h2>The software behind the research.</h2>
          <p>
            Inspect frozen predictions, compare model scores and trace outcomes.
            The local engine retains collection, inference, verification and
            paper-trading workflows.
          </p>
        </div>
        <a className="research-button outline" href="#/engine">
          Open research engine <ArrowRight size={17} />
        </a>
      </section>
    </>
  );
}

function Paper({ slug }: { slug: string }) {
  const paper = papers.find((p) => p.slug === slug);
  if (!paper) return <NotFound />;
  return (
    <div className="paper-layout">
      <aside className="paper-toc">
        <a href="#/papers" className="text-link">
          <ArrowLeft size={15} /> All papers
        </a>
        <span className="research-kicker">In this paper</span>
        <nav aria-label="Paper sections">
          {paper.headings.map((h) => (
            <a href={`#/papers/${slug}/${h.id}`} key={h.id}>
              {h.title}
            </a>
          ))}
        </nav>
        <a href={`research/papers/${slug}.md`} download className="text-link">
          <Download size={15} /> Markdown source
        </a>
        <a href="research/claims.json" className="text-link">
          Evidence manifest <ArrowUpRight size={15} />
        </a>
      </aside>
      <div>
        <div className="paper-meta">
          <span>{paper.category}</span>
          <span>19 October 2026 · {paper.reading_minutes} min read</span>
        </div>
        <article
          className="research-prose"
          dangerouslySetInnerHTML={{ __html: paper.html }}
        />
        <div className="paper-end">
          <BookOpen size={20} />
          <div>
            <h3>Continue the investigation</h3>
            <a className="text-link" href="#/papers">
              Browse all five papers <ArrowRight size={16} />
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

function Evidence() {
  return (
    <>
      <div className="research-page-heading">
        <span className="research-kicker">Methods before claims</span>
        <h1>Evidence you can inspect.</h1>
        <p>
          Small, source-linked extracts accompany every paper. They preserve the
          distinction between historical development, chronological evaluation,
          counterfactuals and hypothetical returns.
        </p>
      </div>
      <div className="evidence-principles">
        <div>
          <span>01 / Provenance</span>
          <h3>Trace every result.</h3>
          <p>
            Original relative paths and SHA-256 hashes accompany the extracts.
            Raw inputs and operational stores remain local.
          </p>
        </div>
        <div>
          <span>02 / Independence</span>
          <h3>Count markets, not copies.</h3>
          <p>
            Overlapping datasets are not additional evidence. Previously
            inspected outcomes are exposed development data.
          </p>
        </div>
        <div>
          <span>03 / Interpretation</span>
          <h3>Forecasts are not fills.</h3>
          <p>
            Proper scores, eligibility, simulated economics and observed paper
            activity answer separate questions.
          </p>
        </div>
      </div>
      <div className="evidence-list">
        {sourceNames.map(([id, title, description]) => (
          <a
            key={id}
            href={`research/sources/${id}.json`}
            target="_blank"
            rel="noreferrer"
          >
            <div>
              <h3>{title}</h3>
              <p>{description}</p>
            </div>
            <span>
              JSON <ArrowUpRight size={18} />
            </span>
          </a>
        ))}
      </div>
      <div className="research-note">
        <h3>What has been reproduced?</h3>
        <p>
          The publication build recalculates the later market-weighted
          Brier/log-loss scores and retained alternative-policy accounting.
          Figures use saved evidence. Model fitting, bootstrap intervals and
          original official-resolution retrieval have not been rerun for this
          publication.
        </p>
        <a className="text-link" href="research/reproduction.json">
          Open reproduction record <ArrowUpRight size={16} />
        </a>
      </div>
    </>
  );
}

function System() {
  return (
    <>
      <div className="research-page-heading">
        <span className="research-kicker">A functioning research system</span>
        <h1>Evidence before execution.</h1>
        <p>
          The engine separates data acquisition, forecasting, eligibility,
          strategy and accounting. A negative result remains useful when its
          inputs and decisions can be audited.
        </p>
      </div>
      <ol className="system-pipeline">
        {[
          [
            "Acquire & retain",
            "Market identities, reference observations, books and source evidence. Event time and receipt time remain distinct.",
          ],
          [
            "Build causal features",
            "Select observations and anchors available by the prediction cutoff. Preserve missingness and exclusion reasons.",
          ],
          [
            "Forecast & compare",
            "Load the frozen model and compare forecasts with matched market probabilities. Separate earlier fitting from later evaluation.",
          ],
          [
            "Verify & evaluate",
            "Check provenance, freshness and fee applicability before unchanged strategy and risk constraints.",
          ],
          [
            "Record & reconcile",
            "Persist decisions, hypothetical fills and independently validated outcomes with restart-safe accounting.",
          ],
        ].map(([title, text]) => (
          <li key={title}>
            <h3>{title}</h3>
            <p>{text}</p>
          </li>
        ))}
      </ol>
      <div className="system-modes">
        <section>
          <span className="research-kicker">Public research demo</span>
          <h2>Frozen and inspectable.</h2>
          <p>
            The browser explores a sanitized historical snapshot. It runs no
            model training, external collection, database writes or trading
            processes. Every view names its cohort.
          </p>
          <a className="text-link" href="#/engine">
            Explore predictions <ArrowRight size={16} />
          </a>
        </section>
        <section>
          <span className="research-kicker">Local research engine</span>
          <h2>The full workflow.</h2>
          <p>
            The repository retains the Python package, command interfaces,
            datasets, frozen artifacts and read-only FastAPI monitor. Collectors
            and paper workflows require the documented local environment. Live
            trading remains disabled.
          </p>
          {localEnabled ? (
            <a className="text-link" href="#Overview">
              Open local monitor <ExternalLink size={16} />
            </a>
          ) : (
            <p className="research-caption">
              Run the local development site to access its monitor. Public
              builds do not connect to operational files.
            </p>
          )}
        </section>
      </div>
      <div className="research-note">
        <h3>Reproduce the publication</h3>
        <pre>
          <code>
            {
              ".\\.venv-execution\\Scripts\\python.exe -B scripts/research/build_publications.py\ncd dashboard/frontend\nnpm ci\nnpm run build"
            }
          </code>
        </pre>
        <p>
          Plotting dependencies are pinned separately. See the repository
          reproduction guide for local data requirements and safe, versioned
          outputs.
        </p>
      </div>
    </>
  );
}

function Engine() {
  const [partition, setPartition] = useState("evaluation");
  const [horizon, setHorizon] = useState("all");
  const [model, setModel] = useState<Model>("raw");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<Row | null>(null);
  const filtered = useMemo(
    () =>
      snapshot.rows.filter(
        (r) =>
          (partition === "all" || r.partition === partition) &&
          (horizon === "all" || r.horizon === Number(horizon)) &&
          `${r.market_id} ${r.target}`
            .toLowerCase()
            .includes(query.toLowerCase()),
      ),
    [partition, horizon, query],
  );
  const result = score(filtered, model),
    market = score(filtered, "market");
  const pageCount = Math.max(1, Math.ceil(filtered.length / 15));
  const safePage = Math.min(page, pageCount - 1);
  return (
    <>
      <div className="research-page-heading">
        <span className="research-kicker">Interactive research engine</span>
        <h1>Look inside the forecasts.</h1>
        <p>
          Inspect the recorded predictions behind the calibration study. Filters
          recalculate scores on the same market/horizon observations for both
          forecasts.
        </p>
      </div>
      <div className="snapshot-banner">
        <div>
          <strong>Historical snapshot · October 12–13, 2026</strong>
          <p>{snapshot.description} No live feed or operational connection.</p>
        </div>
        <a href="research/sources/demo.json" download>
          <Download size={17} /> Download data
        </a>
      </div>
      <div className="explorer-controls">
        <label>
          Partition
          <select
            value={partition}
            onChange={(e) => {
              setPartition(e.target.value);
              setPage(0);
              setSelected(null);
            }}
          >
            <option value="evaluation">Later evaluation</option>
            <option value="calibration">Earlier calibration</option>
            <option value="all">Both · descriptive only</option>
          </select>
        </label>
        <label>
          Horizon
          <select
            value={horizon}
            onChange={(e) => {
              setHorizon(e.target.value);
              setPage(0);
              setSelected(null);
            }}
          >
            <option value="all">All horizons</option>
            {[240, 180, 120, 90, 60, 30].map((h) => (
              <option key={h} value={h}>
                {h} seconds
              </option>
            ))}
          </select>
        </label>
        <label>
          Model
          <select
            value={model}
            onChange={(e) => setModel(e.target.value as Model)}
          >
            {Object.entries(modelNames).map(([key, name]) => (
              <option key={key} value={key}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label className="search-label">
          Search market or UTC time
          <div>
            <Search size={15} />
            <input
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setPage(0);
                setSelected(null);
              }}
              placeholder="market-042 or 14:33"
            />
          </div>
        </label>
      </div>
      <p className="cohort-warning">
        {partition === "evaluation"
          ? "Exploratory chronological holdout, now exposed. This is not an untouched final test."
          : "Calibration rows helped fit these forecasts. These scores describe the fitting data and cannot validate calibration quality."}{" "}
        Each market has equal total weight across its selected horizons.
      </p>
      <div className="explorer-metrics">
        <div>
          <span>Selected cohort</span>
          <strong>
            {filtered.length} <small>observations</small>
          </strong>
          <p>{result.markets} distinct markets</p>
        </div>
        <div>
          <span>{modelNames[model]} · Brier</span>
          <strong>{filtered.length ? fmt(result.brier) : "—"}</strong>
          <p>Log loss {filtered.length ? fmt(result.logLoss) : "—"}</p>
        </div>
        <div>
          <span>Matched market · Brier</span>
          <strong>{filtered.length ? fmt(market.brier) : "—"}</strong>
          <p>Log loss {filtered.length ? fmt(market.logLoss) : "—"}</p>
        </div>
        <div>
          <span>Model − market Brier</span>
          <strong>
            {filtered.length
              ? `${result.brier - market.brier >= 0 ? "+" : ""}${fmt(result.brier - market.brier)}`
              : "—"}
          </strong>
          <p>Positive favors market · descriptive</p>
        </div>
      </div>
      <div className="explorer-chart">
        <div>
          <h2>Same observation. Two probabilities.</h2>
          <p>
            Each point is one recorded market/horizon forecast. The diagonal
            means model and market agree; it does not indicate accuracy.
          </p>
        </div>
        <div
          className="scatter-wrap"
          role="img"
          aria-label="Scatterplot of market versus selected model probabilities. Exact values appear in the accessible table below."
        >
          <ResponsiveContainer width="100%" height={290}>
            <ScatterChart margin={{ top: 12, right: 28, bottom: 20, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                type="number"
                dataKey="market"
                domain={[0, 1]}
                name="Market"
                label={{
                  value: "Market probability YES",
                  position: "bottom",
                  offset: 0,
                }}
              />
              <YAxis
                type="number"
                dataKey={model}
                domain={[0, 1]}
                name={modelNames[model]}
              />
              <Tooltip cursor={{ strokeDasharray: "3 3" }} />
              <ReferenceLine
                segment={[
                  { x: 0, y: 0 },
                  { x: 1, y: 1 },
                ]}
                stroke="#999"
                strokeDasharray="5 4"
              />
              <Scatter
                data={filtered}
                fill="#147d72"
                isAnimationActive={false}
              />
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      </div>
      <div className="explorer-table-wrap">
        <table className="explorer-table">
          <caption>
            Recorded predictions · timestamps in UTC · click Inspect for the
            complete forecast comparison
          </caption>
          <thead>
            <tr>
              <th>Market / target UTC</th>
              <th>Horizon</th>
              <th>Market p(YES)</th>
              <th>{modelNames[model]}</th>
              <th>Registered outcome</th>
              <th>
                <span className="sr-only">Details</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {filtered.slice(safePage * 15, (safePage + 1) * 15).map((r) => (
              <tr key={`${r.market_id}-${r.target}`}>
                <td>
                  <strong>{r.market_id}</strong>
                  <small>{date(r.target)}</small>
                </td>
                <td>{r.horizon}s</td>
                <td>{fmt(r.market)}</td>
                <td>{fmt(r[model])}</td>
                <td>{r.y === 1 ? "YES" : "NO"}</td>
                <td>
                  <button onClick={() => setSelected(r)}>
                    Inspect <ArrowUpRight size={13} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!filtered.length && (
          <p className="empty-cohort">
            No observations match these filters. Scores are unavailable.
          </p>
        )}
      </div>
      <div className="explorer-pagination">
        <span>
          {filtered.length} observations · page {safePage + 1} of {pageCount}
        </span>
        <div>
          <button
            disabled={safePage === 0}
            onClick={() => setPage(safePage - 1)}
          >
            Previous
          </button>
          <button
            disabled={safePage + 1 >= pageCount}
            onClick={() => setPage(safePage + 1)}
          >
            Next
          </button>
        </div>
      </div>
      {selected && (
        <div
          className="observation-detail"
          role="region"
          aria-label="Selected observation"
        >
          <div>
            <span className="research-kicker">
              {selected.market_id} · {selected.horizon}s · {selected.partition}
            </span>
            <button onClick={() => setSelected(null)}>Close</button>
          </div>
          <h2>{date(selected.target)} UTC</h2>
          <p>
            Registered outcome: <strong>{selected.y ? "YES" : "NO"}</strong>.
            Outcome provenance has the retained registry limitations described
            in the paper.
          </p>
          <dl>
            {(
              ["market", "raw", "platt", "isotonic", "combination"] as const
            ).map((k) => (
              <div key={k}>
                <dt>{k === "market" ? "Market midpoint" : modelNames[k]}</dt>
                <dd>{fmt(selected[k])}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
      <div className="research-note">
        <h3>What this demonstration does</h3>
        <p>
          It filters and scores frozen research predictions using equal market
          weights. It does not estimate current prices, rerun inference or
          simulate new trades. Data are already exposed; filtered subsets are
          descriptive, and selecting a favorable horizon here creates no
          independent evidence.
        </p>
        <a className="text-link" href="#/papers/forecast-calibration">
          Read the full methods and uncertainty <ArrowUpRight size={16} />
        </a>
        {localEnabled && (
          <a className="text-link" href="#Overview">
            Open the existing local monitor <ExternalLink size={16} />
          </a>
        )}
      </div>
    </>
  );
}

function NotFound() {
  return (
    <div className="research-page-heading">
      <h1>Page not found.</h1>
      <p>This publication link does not exist.</p>
      <a className="text-link" href="#/papers">
        Browse the collection <ArrowRight size={16} />
      </a>
    </div>
  );
}

export function ResearchApp() {
  const [route, setRoute] = useState(
    () => decodeURIComponent(location.hash.slice(1)) || "/",
  );
  const [dark, setDark] = useState(() => {
    try {
      return localStorage.getItem("polybtc-research-theme") === "dark";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    const listener = () =>
      setRoute(decodeURIComponent(location.hash.slice(1)) || "/");
    window.addEventListener("hashchange", listener);
    return () => window.removeEventListener("hashchange", listener);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    try {
      localStorage.setItem("polybtc-research-theme", dark ? "dark" : "light");
    } catch {
      /* Storage is optional. */
    }
  }, [dark, route]);
  const parts = route.split("/");
  const section = parts[1] || "research";
  useEffect(() => {
    const slug = parts[2];
    const heading = parts[3];
    const p = papers.find((p) => p.slug === slug);
    document.title = p
      ? `${p.title} · PolyBTC Research`
      : "PolyBTC Research · Evidence before execution";
    requestAnimationFrame(() => {
      if (heading)
        document.getElementById(heading)?.scrollIntoView({ block: "start" });
      else window.scrollTo(0, 0);
    });
  }, [route]); // Route determines the document and section.
  if (localPages.includes(route) && localEnabled) return <LocalMonitor />;
  return (
    <div className={`research-site ${dark ? "research-dark" : ""}`}>
      <a
        className="skip-link"
        href="#research-main"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("research-main")?.focus();
        }}
      >
        Skip to content
      </a>
      <header className="research-header">
        <a
          className="research-brand"
          href="#/"
          aria-label="PolyBTC Research home"
        >
          <span className="brand-symbol">
            P<span>↗</span>
          </span>
          <span>
            PolyBTC <b>Research</b>
          </span>
        </a>
        <nav aria-label="Primary navigation">
          {[
            ["research", "Research", "/"],
            ["papers", "Papers", "/papers"],
            ["evidence", "Evidence", "/evidence"],
            ["system", "System", "/system"],
            ["engine", "Engine", "/engine"],
          ].map(([key, label, to]) => (
            <a
              key={key}
              href={`#${to}`}
              aria-current={section === key ? "page" : undefined}
            >
              {label}
            </a>
          ))}
        </nav>
        <div className="research-header-actions">
          {github && /^https:\/\/github\.com\//.test(github) && (
            <a href={github} target="_blank" rel="noreferrer">
              GitHub <ArrowUpRight size={14} />
            </a>
          )}
          <button
            onClick={() => setDark(!dark)}
            aria-label={dark ? "Use light theme" : "Use dark theme"}
          >
            {dark ? <Sun size={18} /> : <Moon size={18} />}
          </button>
        </div>
      </header>
      <main id="research-main" tabIndex={-1} className="research-main">
        {route === "/" ? (
          <Home />
        ) : route === "/papers" ? (
          <>
            <div className="research-page-heading">
              <span className="research-kicker">Technical publications</span>
              <h1>A question-led collection.</h1>
              <p>
                Five focused papers connect data engineering, predictive
                modeling and execution evidence. Negative and inconclusive
                findings are part of the result.
              </p>
            </div>
            <PaperList />
          </>
        ) : section === "papers" && parts[2] ? (
          <Paper slug={parts[2]} />
        ) : route === "/evidence" ? (
          <Evidence />
        ) : route === "/system" ? (
          <System />
        ) : route === "/engine" ? (
          <Engine />
        ) : localPages.includes(route) ? (
          <div className="research-page-heading">
            <h1>The monitor runs locally.</h1>
            <p>
              This public build contains the historical research demonstration.
              Start the repository’s local development site for the read-only
              operational monitor.
            </p>
            <a href="#/engine" className="text-link">
              Open historical demo <ArrowRight size={16} />
            </a>
          </div>
        ) : (
          <NotFound />
        )}
      </main>
      <footer className="research-footer">
        <div>
          <a className="research-brand" href="#/">
            PolyBTC <b>Research</b>
          </a>
          <p>Evidence before execution.</p>
        </div>
        <div>
          <a href="#/evidence">Sources & reproduction</a>
          <a href="#/system">System architecture</a>
          <span>Research demonstration · no real orders</span>
        </div>
        <p>
          Historical evidence through October 2026.
          <br />
          No demonstrated incremental or after-cost edge.
          <br />
          {github
            ? "Repository linked above."
            : "Public repository link and hosted website are not configured."}
        </p>
      </footer>
    </div>
  );
}

// The headline is tied to the same frozen evidence consumed by the explorer.
if (
  Math.abs(forecast.scores.overall.market.brier - 0.12315639460647955) > 1e-12
)
  throw new Error("Headline evidence changed; review publication claims.");
