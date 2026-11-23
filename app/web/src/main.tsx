import { Badge, Empty, Panel, Modal } from "./components/common";
import { UnitCard, DeviceEditor } from "./components/Devices";
import { IncidentList, IncidentDetail } from "./components/Incidents";
import { TemperatureChart } from "./components/Chart";
import { Simulation } from "./pages/Simulation";
import { Analytics } from "./pages/Analytics";
import { live, active, outside, title, duration, time } from "./utils";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  Bell,
  CheckCircle2,
  ChevronRight,
  Cpu,
  FlaskConical,
  LayoutDashboard,
  LogOut,
  MapPin,
  Pause,
  Radio,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Snowflake,
  Wifi,
  X,
  ChartNoAxesCombined,
  AlertTriangle,
} from "lucide-react";
import { connect, csv, disconnect, request } from "./api";
import type { Snapshot, View } from "./types";
import "./styles.css";
const NAV: [View, string, typeof Activity][] = [
  ["overview", "Overview", LayoutDashboard],
  ["devices", "Devices", Cpu],
  ["incidents", "Incidents", Bell],
  ["analytics", "Analytics", ChartNoAxesCombined],
  ["simulation", "Simulation lab", FlaskConical],
];
function App() {
  const [data, setData] = useState<Snapshot | null>(null),
    [view, setView] = useState<View>("overview");
  const [key, setKey] = useState(""),
    [error, setError] = useState(""),
    [success, setSuccess] = useState(""),
    [busy, setBusy] = useState(false);
  const [site, setSite] = useState("all"),
    [filter, setFilter] = useState("all"),
    [selectedUnit, setSelectedUnit] = useState<string | null>(null);
  const [editing, setEditing] = useState(false),
    [selectedIncident, setSelectedIncident] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now() / 1000),
    [polling, setPolling] = useState(false);
  const until = useRef(0),
    signedIn = useRef(false),
    loading = useRef(false),
    mutation = useRef(false),
    offset = useRef(0);
  const refresh = useCallback(async () => {
    if (!signedIn.current || loading.current) return;
    loading.current = true;
    try {
      const snapshot = await request<Snapshot>("state");
      if (signedIn.current) {
        offset.current = snapshot.server_time - Date.now() / 1000;
        setData(snapshot);
      }
    } catch (e) {
      if (signedIn.current) setError((e as Error).message);
    } finally {
      loading.current = false;
    }
  }, []);
  useEffect(() => {
    const tick = window.setInterval(() => {
      setNow(Date.now() / 1000 + offset.current);
      if (signedIn.current && Date.now() >= until.current) setPolling(false);
    }, 1000);
    const poll = window.setInterval(() => {
      if (signedIn.current && Date.now() < until.current) void refresh();
    }, 10000);
    return () => {
      clearInterval(tick);
      clearInterval(poll);
    };
  }, [refresh]);
  useEffect(() => {
    if (!success) return;
    const timer = setTimeout(() => setSuccess(""), 6000);
    return () => clearTimeout(timer);
  }, [success]);
  async function login(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    connect(key.trim());
    setKey("");
    try {
      const snapshot = await request<Snapshot>("state");
      signedIn.current = true;
      offset.current = snapshot.server_time - Date.now() / 1000;
      setData(snapshot);
      until.current = Date.now() + 600000;
      setPolling(true);
    } catch (e) {
      disconnect();
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function logout() {
    signedIn.current = false;
    disconnect();
    setData(null);
    setError("");
    setSuccess("");
    setSelectedUnit(null);
    setSelectedIncident(null);
    setPolling(false);
  }
  async function mutate(path: string, body: unknown, message: string) {
    if (mutation.current) return;
    mutation.current = true;
    until.current = Date.now() + 600000;
    setPolling(true);
    setBusy(true);
    setError("");
    try {
      await request(path, body);
      if (signedIn.current) {
        setSuccess(message);
        await refresh();
      }
    } catch (e) {
      if (signedIn.current) setError((e as Error).message);
      throw e;
    } finally {
      mutation.current = false;
      setBusy(false);
    }
  }
  const safely = (promise: Promise<void>) => {
    void promise.catch(() => {});
  };
  function resume() {
    until.current = Date.now() + 600000;
    setPolling(true);
    void refresh();
  }
  if (!data)
    return (
      <main className="login-shell">
        <section className="login-story">
          <div className="brand">
            <Snowflake size={28} />
            coldchain<span>MONITOR</span>
          </div>
          <div>
            <span className="eyebrow">EVERY DEGREE MATTERS</span>
            <h1>
              Keep your cool.
              <br />
              We’ll keep watch.
            </h1>
            <p>
              One workspace for your cold-storage devices, incident response and
              the moments that matter.
            </p>
            <div className="login-points">
              <span>
                <ShieldCheck size={18} />
                Reliable detection
              </span>
              <span>
                <Bell size={18} />
                Timely alerts
              </span>
              <span>
                <FlaskConical size={18} />
                Realistic simulations
              </span>
            </div>
          </div>
        </section>
        <section className="login-form-wrap">
          <form onSubmit={login} className="login-form">
            <span className="eyebrow">OPERATIONS WORKSPACE</span>
            <h2>Welcome back.</h2>
            <p className="muted">
              Connect to monitor your devices and explore the simulation lab.
            </p>
            <label>
              Operator access key
              <input
                autoComplete="off"
                type="password"
                required
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder="Enter your workspace key"
              />
            </label>
            {error && (
              <div className="notice warning" role="alert">
                {error}
              </div>
            )}
            <button className="button primary full" disabled={busy}>
              {busy ? "Connecting…" : "Open workspace"}
              <ArrowRight size={17} />
            </button>
          </form>
        </section>
      </main>
    );
  const units = data.units.filter((u) => site === "all" || u.site_id === site);
  const incidents = units
    .flatMap((u) => u.incidents)
    .sort((a, b) => b.opened_at - a.opened_at);
  const openIncidents = incidents.filter(active);
  const unit = data.units.find((u) => u.unit_id === selectedUnit);
  const incident = data.units
    .flatMap((u) => u.incidents)
    .find((i) => i.incident_id === selectedIncident);
  const incidentUnit =
    incident && data.units.find((u) => u.unit_id === incident.unit_id);
  const online = units.filter((u) => u.connection === "online").length;
  const visibleUnits = units.filter((u) =>
    filter === "all" || filter === "attention"
      ? filter !== "attention" || outside(u) || u.connection === "offline"
      : u.kind === filter,
  );
  const session =
    data.session && data.session.deadline <= now && live(data.session)
      ? { ...data.session, status: "expired" }
      : data.session;
  const navigate = (next: View) => {
    setView(next);
    setError("");
  };
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <Snowflake size={25} />
          coldchain<span>MONITOR</span>
        </div>
        <span className="nav-caption">WORKSPACE</span>
        <nav aria-label="Main navigation">
          {NAV.map(([id, name, Icon]) => (
            <button
              key={id}
              className={view === id ? "nav-link selected" : "nav-link"}
              onClick={() => navigate(id)}
            >
              <Icon size={18} />
              <span>{name}</span>
              {id === "incidents" && !!openIncidents.length && (
                <b>{openIncidents.length}</b>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <button className="nav-link" onClick={logout}>
            <LogOut size={17} />
            Disconnect
          </button>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <span className="breadcrumb">
            Workspace <ChevronRight size={13} />{" "}
            <strong>{NAV.find((n) => n[0] === view)?.[1]}</strong>
          </span>
          <div>
            <Badge tone="green">
              <ShieldCheck size={12} />
              Authenticated
            </Badge>
            <button
              className="icon-button mobile-logout"
              aria-label="Disconnect workspace"
              title="Disconnect"
              onClick={logout}
            >
              <LogOut size={16} />
            </button>
            <span className="avatar" title="Shared operator">
              OP
            </span>
          </div>
        </header>
        <div className="content">
          <div className="page-heading">
            <div>
              <span className="eyebrow">YOUR COLD CHAIN, CONNECTED</span>
              <h1>
                {view === "overview"
                  ? "A little oversight. A lot of peace of mind."
                  : view === "devices"
                    ? "A place for every device."
                    : view === "incidents"
                      ? "From alert to action."
                      : view === "analytics"
                        ? "History, made useful."
                        : "Make the unexpected, expected."}
              </h1>
              <p>
                {view === "overview"
                  ? "Keep an eye on every degree, across your entire workspace."
                  : view === "devices"
                    ? "Manage your devices and temperature limits."
                    : view === "incidents"
                      ? "Understand what happened, coordinate a response and follow recovery."
                      : view === "analytics"
                        ? "Explore recorded conditions, coverage and operational response."
                        : "Test failures safely before they happen in the real world."}
              </p>
            </div>
            <div className="page-actions">
              <label className="site-select">
                <MapPin size={15} />
                <select
                  aria-label="Site filter"
                  value={site}
                  onChange={(e) => setSite(e.target.value)}
                >
                  <option value="all">All sites</option>
                  {[...new Set(data.units.map((u) => u.site_id))].map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </label>
              <button
                className="icon-button"
                title="Refresh and resume live updates"
                aria-label="Refresh workspace"
                onClick={resume}
              >
                <RefreshCw size={17} />
              </button>
            </div>
          </div>
          {error && (
            <div className="notice warning" role="alert">
              <AlertTriangle size={18} />
              {error}
              <button
                className="icon-button push"
                aria-label="Dismiss error"
                onClick={() => setError("")}
              >
                <X size={15} />
              </button>
            </div>
          )}
          {success && (
            <div className="notice success" role="status">
              <CheckCircle2 size={18} />
              {success}
            </div>
          )}
          {!polling && (
            <div className="notice">
              <Pause size={17} />
              Live updates paused after ten minutes.
              <button className="text-button" onClick={resume}>
                Resume updates
              </button>
            </div>
          )}
          {!data.ingestion_enabled && (
            <div className="notice warning">
              Sensor ingestion is currently paused.
            </div>
          )}
          {live(session) && view !== "simulation" && (
            <button
              className="session-banner"
              onClick={() => navigate("simulation")}
            >
              <Radio size={18} />
              <strong>
                {session?.mode === "simulation" ? "Simulation" : "Monitoring"}{" "}
                session running
              </strong>
              <span>
                {duration((session?.deadline || now) - now)} remaining
              </span>
              <ChevronRight className="push" size={17} />
            </button>
          )}
          {view === "overview" && (
            <>
              <div className="stats-grid">
                <Panel>
                  <span className="stat-label">
                    <Cpu size={16} />
                    Configured devices
                  </span>
                  <strong className="stat-value">{units.length}</strong>
                  <small>
                    {new Set(units.map((u) => u.site_id)).size} sites in view
                  </small>
                </Panel>
                <Panel>
                  <span className="stat-label">
                    <Wifi size={16} />
                    Fresh readings
                  </span>
                  <strong className="stat-value">
                    {online}
                    <span> devices</span>
                  </strong>
                  <small>Reporting on time</small>
                </Panel>
                <Panel>
                  <span className="stat-label">
                    <Bell size={16} />
                    Open incidents
                  </span>
                  <strong
                    className={`stat-value ${openIncidents.length ? "amber-text" : ""}`}
                  >
                    {openIncidents.length}
                  </strong>
                  <small>
                    {openIncidents.filter((i) => !i.acknowledged).length}{" "}
                    awaiting acknowledgement
                  </small>
                </Panel>
                <Panel>
                  <span className="stat-label">
                    <Radio size={16} />
                    Physical devices
                  </span>
                  <strong className="stat-value">
                    {units.filter((u) => u.source === "physical").length}
                  </strong>
                  <small>Configured for sensor readings</small>
                </Panel>
              </div>
              <div className="section-heading">
                <div>
                  <span className="eyebrow">TEMPERATURE AT A GLANCE</span>
                  <h2>
                    Your devices{" "}
                    <span className="count-pill">{units.length}</span>
                  </h2>
                </div>
                <div className="filters">
                  {["all", "fridge", "freezer", "attention"].map((f) => (
                    <button
                      key={f}
                      className={filter === f ? "active" : ""}
                      onClick={() => setFilter(f)}
                    >
                      {f === "all"
                        ? "All devices"
                        : f === "attention"
                          ? "Needs attention"
                          : title(f) + "s"}
                    </button>
                  ))}
                </div>
              </div>
              <div className="unit-grid">
                {visibleUnits.map((u) => (
                  <UnitCard
                    key={u.unit_id}
                    unit={u}
                    select={() => {
                      setSelectedUnit(u.unit_id);
                      setEditing(false);
                    }}
                  />
                ))}
              </div>
              {!visibleUnits.length && (
                <Empty>No devices match this filter.</Empty>
              )}
              <div className="overview-bottom">
                <Panel>
                  <div className="panel-heading">
                    <h2>Needs your attention</h2>
                    <button
                      className="text-button"
                      onClick={() => navigate("incidents")}
                    >
                      View all <ArrowRight size={14} />
                    </button>
                  </div>
                  <IncidentList
                    incidents={openIncidents}
                    units={units}
                    select={(i) => setSelectedIncident(i.incident_id)}
                  />
                </Panel>
                <Panel className="lab-teaser">
                  <span className="teaser-icon">
                    <FlaskConical size={25} />
                  </span>
                  <span className="eyebrow">THE SIMULATION LAB</span>
                  <h2>
                    What if a fridge door
                    <br />
                    was left open?
                  </h2>
                  <p>
                    Rehearse a realistic failure and follow the response from
                    first reading to recovery.
                  </p>
                  <button
                    className="button primary"
                    onClick={() => navigate("simulation")}
                  >
                    Explore scenarios <ArrowRight size={16} />
                  </button>
                </Panel>
              </div>
              <Panel>
                <div className="panel-heading">
                  <div>
                    <span className="eyebrow">SITE LAYOUT</span>
                    <h2>Your workspace, at a glance</h2>
                  </div>
                  <Badge>Schematic layout</Badge>
                </div>
                <div className="site-layout">
                  {units.map((u) => (
                    <button
                      key={u.unit_id}
                      className={
                        outside(u) ? "site-device attention" : "site-device"
                      }
                      onClick={() => {
                        setSelectedUnit(u.unit_id);
                        setEditing(false);
                      }}
                    >
                      <Snowflake size={25} />
                      <strong>{u.name}</strong>
                      <span>
                        {u.temperature === null
                          ? "No reading"
                          : `${u.temperature.toFixed(1)}°C`}
                      </span>
                      <small>{u.site_id}</small>
                    </button>
                  ))}
                </div>
              </Panel>
            </>
          )}
          {view === "devices" && (
            <>
              <Panel>
                <div className="panel-heading">
                  <div>
                    <span className="eyebrow">FLEET REGISTRY</span>
                    <h2>Your devices</h2>
                  </div>
                  <Badge>{units.length} in view</Badge>
                </div>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Device</th>
                        <th>Site</th>
                        <th>Source</th>
                        <th>Rule</th>
                        <th>Connection</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {units.map((u) => (
                        <tr key={u.unit_id}>
                          <td>
                            <strong>{u.name}</strong>
                            <small>
                              {u.unit_id} · {u.kind}
                            </small>
                          </td>
                          <td>{u.site_id}</td>
                          <td>
                            <Badge
                              tone={
                                u.source === "physical" ? "blue" : "neutral"
                              }
                            >
                              {title(u.source)}
                            </Badge>
                          </td>
                          <td>
                            {u.direction === "max" ? "≤" : "≥"} {u.threshold}°C
                            <small>Every {u.interval_s}s</small>
                          </td>
                          <td>
                            <Badge
                              tone={
                                u.connection === "online"
                                  ? "green"
                                  : u.connection === "offline"
                                    ? "amber"
                                    : "neutral"
                              }
                            >
                              {title(u.connection)}
                            </Badge>
                          </td>
                          <td>
                            <button
                              className="button secondary compact"
                              onClick={() => {
                                setSelectedUnit(u.unit_id);
                                setEditing(true);
                              }}
                            >
                              <Settings2 size={14} />
                              Configure
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>
            </>
          )}
          {view === "incidents" && (
            <Panel>
              <div className="panel-heading">
                <div>
                  <span className="eyebrow">RESPONSE CENTRE</span>
                  <h2>Recent incidents</h2>
                </div>
                <Badge>{openIncidents.length} open</Badge>
              </div>
              <IncidentList
                incidents={incidents}
                units={units}
                select={(i) => setSelectedIncident(i.incident_id)}
              />
              <p className="panel-footnote">
                Showing up to five recent incidents per device.
              </p>
            </Panel>
          )}
          {view === "simulation" && (
            <Simulation
              units={units}
              session={session}
              now={now}
              busy={busy}
              run={(body) => mutate("sessions/start", body, "Session started.")}
              stop={() =>
                safely(
                  mutate(
                    "sessions/stop",
                    { session_id: session?.session_id },
                    "Stop requested; monitoring disabled.",
                  ),
                )
              }
            />
          )}
          {view === "analytics" && (
            <Analytics
              units={units}
              report={data.report}
              busy={busy}
              generate={(body) =>
                mutate(
                  "reports",
                  body,
                  "Historical report requested. Results update automatically.",
                )
              }
            />
          )}
          <footer>
            <span>
              <Snowflake size={14} />
              Coldchain Monitor
            </span>
            <span>
              {polling ? (
                <>
                  <span className="status-dot online" />
                  Refreshes every 10s
                </>
              ) : (
                "Updates paused"
              )}{" "}
              · {time(data.server_time)}
            </span>
          </footer>
        </div>
      </main>
      {unit && (
        <Modal
          label={`Device ${unit.name}`}
          wide
          close={() => {
            setSelectedUnit(null);
          }}
        >
          {error && (
            <div className="notice warning" role="alert">
              {error}
            </div>
          )}
          <div className="detail-heading">
            <span className="eyebrow">
              {unit.unit_id} · {unit.site_id}
            </span>
            <h2>{unit.name}</h2>
            <div className="detail-tabs">
              <button
                className={!editing ? "active" : ""}
                onClick={() => {
                  setEditing(false);
                }}
              >
                Live view
              </button>
              <button
                className={editing ? "active" : ""}
                onClick={() => {
                  setEditing(true);
                }}
              >
                Settings
              </button>
            </div>
          </div>
          {editing ? (
            <DeviceEditor
              key={`${unit.unit_id}-${unit.revision}`}
              unit={unit}
              busy={busy}
              save={(body) => mutate("devices", body, "Device settings saved.")}
            />
          ) : (
            <>
              <div className="device-summary">
                <div>
                  <span className="muted small">LATEST TEMPERATURE</span>
                  <strong>
                    {unit.temperature === null
                      ? "—"
                      : unit.temperature.toFixed(1)}
                    <span>°C</span>
                  </strong>
                </div>
                <Badge tone={outside(unit) ? "amber" : "green"}>
                  {unit.temperature === null
                    ? "No readings"
                    : outside(unit)
                      ? "Outside configured limit"
                      : unit.temperature === null
                        ? "Awaiting first reading"
                        : "Within configured limit"}
                </Badge>
              </div>
              <TemperatureChart unit={unit} large />
              <div className="chart-caption">
                <span>
                  Last {unit.history.length} readings ·{" "}
                  {unit.direction === "max" ? "≤" : "≥"} {unit.threshold}°C
                </span>
                <button
                  className="text-button"
                  onClick={() =>
                    csv(`${unit.unit_id}-readings.csv`, [
                      ["observed_at", "temperature"],
                      ...unit.history,
                    ])
                  }
                >
                  <ArrowDownToLine size={14} />
                  Export readings
                </button>
              </div>
              <div className="device-facts">
                <span>
                  Source<strong>{title(unit.source)}</strong>
                </span>
                <span>
                  Reporting interval<strong>{unit.interval_s}s</strong>
                </span>
                <span>
                  Offline alerts
                  <strong>
                    {unit.monitoring ? "Monitoring active" : "Inactive"}
                  </strong>
                </span>
              </div>
              {unit.source === "simulation" && (
                <form
                  className="manual-reading"
                  onSubmit={(e) => {
                    e.preventDefault();
                    const form = new FormData(e.currentTarget);
                    safely(
                      mutate(
                        "readings",
                        {
                          schema_version: 1,
                          reading_id: crypto.randomUUID(),
                          unit_id: unit.unit_id,
                          site_id: unit.site_id,
                          observed_at: new Date().toISOString(),
                          temperature: Number(form.get("temperature")),
                        },
                        "Reading accepted.",
                      ),
                    );
                  }}
                >
                  <label>
                    Send a manual reading
                    <input
                      type="number"
                      name="temperature"
                      min={-100}
                      max={100}
                      step="0.1"
                      defaultValue={
                        unit.threshold - (unit.direction === "max" ? 1 : -1)
                      }
                      required
                    />
                  </label>
                  <button
                    className="button primary"
                    disabled={busy || live(session)}
                  >
                    Send reading <ArrowRight size={15} />
                  </button>
                </form>
              )}
            </>
          )}
        </Modal>
      )}
      {incident && incidentUnit && (
        <IncidentDetail
          key={incident.incident_id}
          incident={incident}
          error={error}
          unit={incidentUnit}
          now={now}
          busy={busy}
          close={() => setSelectedIncident(null)}
          mutate={(path, body, message) => mutate(path, body, message)}
        />
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
