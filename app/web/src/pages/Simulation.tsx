import { SimulationOutcomes } from "../components/SimulationOutcomes";
import { useState } from "react";
import {
  Check,
  CheckCircle2,
  ShieldCheck,
  Radio,
  Pause,
  Play,
  Clock3,
  Activity,
} from "lucide-react";
import type { Unit, Session } from "../types";
import { Panel, Badge } from "../components/common";
import { SCENARIOS } from "../scenarios";
import { live, duration, title } from "../utils";
export function Simulation({
  units,
  session,
  now,
  busy,
  run,
  stop,
}: {
  units: Unit[];
  session: Session | null;
  now: number;
  busy: boolean;
  run: (body: unknown) => Promise<void>;
  stop: () => void;
}) {
  const [scenario, setScenario] = useState("door_open"),
    [mode, setMode] = useState("simulation");
  const [selected, setSelected] = useState<string[] | null>(null),
    [seconds, setSeconds] = useState(600),
    [interval, setIntervalValue] = useState(30);
  const available = units.filter(
    (u) =>
      u.enabled &&
      u.source === (mode === "simulation" ? "simulation" : "physical"),
  );
  const chosen = (selected || []).filter((id) =>
    available.some((u) => u.unit_id === id),
  );
  const selectedIds =
    selected === null ? available.map((u) => u.unit_id) : chosen;
  const running = live(session);
  const steps = Math.min(
    100,
    Math.floor(
      seconds /
        (mode === "simulation"
          ? Math.max(2, Math.ceil(interval / Math.max(1, selectedIds.length)))
          : 15),
    ),
  );
  return (
    <div className="lab-layout">
      <div>
        {session && <SimulationOutcomes session={session} units={units} />}
        <div className="section-heading">
          <div>
            <span className="eyebrow">REHEARSE THE REAL WORLD</span>
            <h2>What happens if…</h2>
          </div>
          <Badge tone="green">Live processing pipeline</Badge>
        </div>
        <p className="muted">
          Create a controlled failure. Watch the same detection, alerts and
          recovery used for physical devices.
        </p>
        <div className="scenario-grid">
          {SCENARIOS.map(([id, name, description, Icon]) => (
            <button
              key={id}
              className={`scenario-card ${scenario === id ? "selected" : ""}`}
              onClick={() => setScenario(id)}
              disabled={running}
            >
              <span className="scenario-symbol">
                <Icon size={23} />
              </span>
              <span className="selection-mark">
                {scenario === id && <Check size={13} />}
              </span>
              <h3>{name}</h3>
              <p>{description}</p>
            </button>
          ))}
        </div>
        <Panel className="expectation">
          <ShieldCheck size={22} />
          <div>
            <strong>Repeatable scenarios. Real alerts.</strong>
            <p>
              Only the first selected unit receives the failure scenario; the
              others provide a normal baseline. Temperature curves are a
              deterministic approximation. Email alerts are real.
            </p>
          </div>
        </Panel>
      </div>
      <Panel className="session-panel">
        <span className="eyebrow">SESSION CONTROLS</span>
        <h2>{running ? "Session in progress" : "Prepare your run"}</h2>
        {running && session ? (
          <>
            <div className="running-orb">
              <Radio size={32} />
            </div>
            <h3>
              {session.mode === "monitor"
                ? "Physical sensor monitoring"
                : SCENARIOS.find((s) => s[0] === session.scenario)?.[1]}
            </h3>
            <p className="muted">
              {duration(session.deadline - now)} remaining ·{" "}
              {session.units.length} devices
            </p>
            <progress value={session.processed_steps} max={session.max_steps} />
            <div className="progress-label">
              <span>
                {session.processed_steps} / {session.max_steps} steps
              </span>
              <strong>{session.submitted} sent</strong>
            </div>
            <div className="session-counts">
              <span>
                <strong>{session.skipped}</strong> intentionally skipped
              </span>
              <span>
                <strong>{session.interval_s}s</strong> per-unit interval
              </span>
            </div>
            <button
              className="button danger full"
              disabled={busy || session.status === "stopping"}
              onClick={stop}
            >
              <Pause size={16} />
              {session.status === "stopping" ? "Stopping…" : "Stop session"}
            </button>
            <p className="small muted">
              Stopping disables offline monitoring immediately. One request
              already in flight can still complete.
            </p>
          </>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void run({
                request_id: crypto.randomUUID(),
                mode,
                scenario,
                units: selectedIds,
                duration_s: seconds,
                interval_s: interval,
              }).catch(() => {});
            }}
          >
            <label>
              Session type
              <select
                value={mode}
                onChange={(e) => {
                  setMode(e.target.value);
                  setSelected(null);
                }}
              >
                <option value="simulation">Generate simulated readings</option>
                <option value="monitor">Monitor physical devices only</option>
              </select>
            </label>
            <fieldset>
              <legend>Devices · first selection is the fault target</legend>
              {available.map((u) => (
                <label className="checkbox" key={u.unit_id}>
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(u.unit_id)}
                    onChange={(e) =>
                      setSelected(
                        e.target.checked
                          ? [
                              ...selectedIds.filter((id) => id !== u.unit_id),
                              u.unit_id,
                            ]
                          : selectedIds.filter((id) => id !== u.unit_id),
                      )
                    }
                  />
                  {u.name}
                </label>
              ))}
              {!available.length && (
                <p className="small muted">
                  Configure an enabled{" "}
                  {mode === "simulation" ? "simulation" : "physical"} device
                  first.
                </p>
              )}
            </fieldset>
            <label>
              Duration
              <select
                value={seconds}
                onChange={(e) => setSeconds(Number(e.target.value))}
              >
                <option value={180}>3 minutes</option>
                <option value={300}>5 minutes</option>
                <option value={600}>10 minutes</option>
              </select>
            </label>
            {mode === "simulation" && (
              <label>
                Reading interval
                <select
                  value={interval}
                  onChange={(e) => setIntervalValue(Number(e.target.value))}
                >
                  <option value={30}>Standard · 30 seconds per unit</option>
                  <option value={10}>Faster demo · 10 seconds per unit</option>
                </select>
              </label>
            )}
            <div className="run-summary">
              <span>
                <Clock3 size={15} /> {duration(seconds)} maximum
              </span>
              <span>
                <Activity size={15} /> Up to {mode === "simulation" ? steps : 0}{" "}
                readings
              </span>
            </div>
            <button
              className="button primary full"
              disabled={busy || !selectedIds.length}
            >
              <Play size={16} />
              {mode === "simulation" ? "Start simulation" : "Start monitoring"}
            </button>
            <p className="small muted">
              Runs on the backend, including when this tab closes. The deadline
              and request limit stop each session automatically. One session at
              a time.
            </p>
          </form>
        )}
        {!running && session && (
          <div className="last-run">
            <CheckCircle2 size={16} /> Last session: {title(session.status)} ·{" "}
            {session.submitted} readings
          </div>
        )}
      </Panel>
    </div>
  );
}
