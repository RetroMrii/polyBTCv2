import { useEffect, useState } from "react";
import {
  Activity,
  ArrowUpRight,
  BarChart3,
  CheckCheck,
  ChevronRight,
  CircleDot,
  Database,
  Gauge,
  LayoutDashboard,
  ListFilter,
  Menu,
  Radio,
  Settings,
  ShieldCheck,
} from "lucide-react";
import { MotionConfig, motion } from "motion/react";
import { Badge, Empty, PollState, SourceState, time } from "./components";
import { useClock, usePoll } from "./hooks";
import {
  HealthPage,
  JournalPage,
  MarketOverview,
  PerformancePage,
  ResolutionsPage,
  SettingsPage,
} from "./pages";
import type { Overview, Preferences } from "./types";
import "./style.css";

const navigation = [
  { name: "Overview", icon: LayoutDashboard },
  { name: "Live Market", icon: Activity },
  { name: "Predictions", icon: BarChart3 },
  { name: "Decisions", icon: ListFilter },
  { name: "Performance", icon: Gauge },
  { name: "Resolutions", icon: CheckCheck },
  { name: "System Health", icon: Radio },
  { name: "Settings", icon: Settings },
];
const defaults: Preferences = {
  refresh: 2,
  pageSize: 25,
  window: 15,
  timezone: "UTC",
  density: "compact",
  animations: true,
  theme: "dark",
};
function readPrefs(): Preferences {
  try {
    const parsed = JSON.parse(
      localStorage.getItem("polybtc-monitor-preferences") || "{}",
    );
    const p = { ...defaults, ...parsed };
    return {
      refresh: [1, 2, 5, 10].includes(p.refresh) ? p.refresh : 2,
      pageSize: [10, 25, 50, 100].includes(p.pageSize) ? p.pageSize : 25,
      window: [5, 15, 30, 60].includes(p.window) ? p.window : 15,
      timezone: ["UTC", "local", "Asia/Jerusalem"].includes(p.timezone)
        ? p.timezone
        : "UTC",
      density: p.density === "comfortable" ? "comfortable" : "compact",
      theme: p.theme === "light" ? "light" : "dark",
      animations: p.animations !== false,
    };
  } catch {
    return defaults;
  }
}
export function LocalMonitor() {
  const [prefs, setPrefs] = useState(readPrefs);
  const [page, setPage] = useState(
    () => decodeURIComponent(location.hash.slice(1)) || "Overview",
  );
  const [sidebar, setSidebar] = useState(false);
  const result = usePoll<Overview>(
    `/api/overview?minutes=${prefs.window}`,
    prefs.refresh * 1000,
  );
  const clock = useClock();
  const data = result.data;
  useEffect(() => {
    try {
      localStorage.setItem(
        "polybtc-monitor-preferences",
        JSON.stringify(prefs),
      );
    } catch {
      /* Browser storage may be disabled. */
    }
    document.documentElement.dataset.theme = prefs.theme;
    document.documentElement.dataset.density = prefs.density;
    document.documentElement.dataset.motion = String(prefs.animations);
  }, [prefs]);
  useEffect(() => {
    const listener = () =>
      setPage(decodeURIComponent(location.hash.slice(1)) || "Overview");
    window.addEventListener("hashchange", listener);
    return () => window.removeEventListener("hashchange", listener);
  }, []);
  const connected = !result.error && !!data;
  return (
    <MotionConfig reducedMotion={prefs.animations ? "user" : "always"}>
      <div className="app-shell">
        <aside className={`sidebar ${sidebar ? "open" : ""}`}>
          <a className="brand" href="#Overview">
            <div className="brand-mark">
              P<span>↗</span>
            </div>
            <div>
              POLY<span>BTC</span>
              <small>
                RESEARCH TERMINAL <b>v2</b>
              </small>
            </div>
          </a>
          <div className="workspace-label">
            WORKSPACE <Badge>LOCAL</Badge>
          </div>
          <nav aria-label="Main navigation">
            {navigation.map(({ name, icon: Icon }, i) => (
              <a
                key={name}
                href={`#${encodeURIComponent(name)}`}
                className={`${page === name ? "active" : ""} ${i === 6 ? "nav-separator" : ""}`}
                onClick={() => setSidebar(false)}
                aria-current={page === name ? "page" : undefined}
              >
                <Icon size={17} />
                <span>{name}</span>
                {page === name && <ChevronRight size={13} />}
              </a>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <div className="environment">
              <ShieldCheck size={17} />
              <div>
                <strong>
                  {data?.mode === "PAPER EXECUTION"
                    ? "Paper environment"
                    : "Read-only monitor"}
                </strong>
                <small>No real orders · read only</small>
              </div>
            </div>
            <div className="sidebar-meta">
              <Database size={13} />
              Local data adapters<span>v1.0</span>
            </div>
          </div>
        </aside>
        <div className="main-shell">
          <header className="topbar">
            <div className="inline">
              <button
                className="icon-button mobile-menu"
                aria-label="Toggle navigation"
                onClick={() => setSidebar(!sidebar)}
              >
                <Menu size={19} />
              </button>
              <span className="breadcrumb">
                Workspace <ChevronRight size={12} /> <b>{page}</b>
              </span>
            </div>
            <div className="topbar-right">
              <a className="docs-link" href="#/">Research publications</a>
              <Badge tone="cyan">
                <ShieldCheck size={11} />
                {data?.mode ?? "READ ONLY"}
              </Badge>
              <span className={`connection ${connected ? "good" : "warn"}`}>
                <CircleDot size={12} />
                {connected ? "API connected" : "Disconnected"}
              </span>
              <span className="clock">
                {time(new Date(clock).toISOString(), prefs.timezone)}{" "}
                <small>{prefs.timezone}</small>
              </span>
            </div>
          </header>
          <main>
            <div className="page-title">
              <div>
                <span className="eyebrow">POLYBTC / LOCAL ENGINE</span>
                <h1>{page === "Overview" ? "Trading overview" : page}</h1>
                <p>
                  {page === "Overview"
                    ? "Paper PnL, positions and capital at risk · HGB3 v2."
                    : "Evidence-driven monitoring · BTC five-minute markets"}
                </p>
              </div>
              <a
                className="docs-link"
                href="http://127.0.0.1:8001/api/docs"
                target="_blank"
                rel="noreferrer"
              >
                Read-only API <ArrowUpRight size={14} />
              </a>
            </div>
            <PollState {...result} />
            <div className="status-strip">
              <span>
                <i className="dot cyan" />
                LOCAL MONITOR
              </span>
              <SourceState
                source={data?.health.sources.collector}
                label="Collector"
              />
              <SourceState
                source={data?.health.sources.journal_activity}
                label="Journal"
              />
              <SourceState
                source={data?.health.sources.last_resolution}
                label="Resolution"
              />
              <span className="prediction-rate">
                Predictions · {data?.health.prediction_count_15m ?? "—"} / 15m
              </span>
              <span className="last-sync">
                Last API success{" "}
                {result.lastSuccess
                  ? time(result.lastSuccess.toISOString(), prefs.timezone)
                  : "—"}
              </span>
            </div>
            <motion.div
              key={page}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: prefs.animations ? 0.18 : 0 }}
              className="page-content"
            >
              {page === "Settings" ? (
                <SettingsPage prefs={prefs} setPrefs={setPrefs} />
              ) : !data ? (
                <div className="loading-panel">
                  <div className="skeleton" />
                  <div className="skeleton" />
                  <Empty>
                    {result.error
                      ? "Start the dashboard backend on 127.0.0.1:8001 to load project data."
                      : "Connecting to local read-only data sources…"}
                  </Empty>
                </div>
              ) : page === "Overview" ? (
                <MarketOverview data={data} prefs={prefs} />
              ) : page === "Live Market" ? (
                <MarketOverview data={data} prefs={prefs} detailed />
              ) : page === "Predictions" ? (
                <JournalPage
                  key="predictions"
                  prefs={prefs}
                  overview={data}
                  predictions
                />
              ) : page === "Decisions" ? (
                <JournalPage key="decisions" prefs={prefs} overview={data} />
              ) : page === "Performance" ? (
                <PerformancePage />
              ) : page === "Resolutions" ? (
                <ResolutionsPage prefs={prefs} />
              ) : page === "System Health" ? (
                <HealthPage overview={data} prefs={prefs} />
              ) : (
                <Empty>Unknown page. Select a page from the navigation.</Empty>
              )}
            </motion.div>
            <footer className="app-footer">
              <span>
                POLYBTC v2 <b>·</b> Evidence before execution
              </span>
              <span>
                Read-only monitoring <b>·</b> No trading controls
              </span>
            </footer>
          </main>
        </div>
      </div>
    </MotionConfig>
  );
}

