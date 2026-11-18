import { useState, type FormEvent } from "react";
import {
  MoreHorizontal,
  Snowflake,
  Thermometer,
  MapPin,
  Check,
} from "lucide-react";
import type { Unit } from "../types";
import { Badge } from "./common";
import { outside, title } from "../utils";
function Sparkline({ unit }: { unit: Unit }) {
  const values = unit.history.map((p) => p[1]);
  if (values.length < 2)
    return <div className="spark-placeholder">Waiting for readings</div>;
  const min = Math.min(...values, unit.threshold) - 0.5,
    span = Math.max(...values, unit.threshold) - min + 0.5;
  const points = values
    .map(
      (v, i) =>
        `${(i * 200) / (values.length - 1)},${43 - ((v - min) * 38) / span}`,
    )
    .join(" ");
  return (
    <svg
      viewBox="0 0 200 48"
      className={`spark ${outside(unit) ? "warn" : ""}`}
      aria-hidden="true"
    >
      <line
        x1="0"
        x2="200"
        y1={43 - ((unit.threshold - min) * 38) / span}
        y2={43 - ((unit.threshold - min) * 38) / span}
        strokeDasharray="3 4"
      />
      <polyline points={points} />
    </svg>
  );
}
export function UnitCard({ unit, select }: { unit: Unit; select: () => void }) {
  return (
    <button
      className={`unit-card ${outside(unit) ? "attention" : ""}`}
      onClick={select}
    >
      <div className="unit-card-top">
        <span className="device-icon">
          {unit.kind === "freezer" ? (
            <Snowflake size={20} />
          ) : (
            <Thermometer size={20} />
          )}
        </span>
        <Badge tone={unit.source === "physical" ? "blue" : "neutral"}>
          {unit.source === "physical" ? "Physical" : "Simulated"}
        </Badge>
        <MoreHorizontal size={19} />
      </div>
      <h3>{unit.name}</h3>
      <span className="muted small">
        <MapPin size={12} /> {unit.site_id}
      </span>
      <div className="temperature">
        {unit.temperature === null ? "—" : unit.temperature.toFixed(1)}
        <span>°C</span>
      </div>
      <div className="card-rule">
        Target {unit.direction === "max" ? "≤" : "≥"} {unit.threshold}°C{" "}
        <span>
          {outside(unit)
            ? `${unit.consecutive}/3 outside`
            : unit.temperature === null
              ? "Awaiting first reading"
              : "Within configured limit"}
        </span>
      </div>
      <Sparkline unit={unit} />
      <div className="card-footer">
        <span className={`status-dot ${unit.connection}`} />
        {title(unit.connection)}
        <span className="push">
          {unit.observed_at
            ? new Date(unit.observed_at).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })
            : "No data yet"}
        </span>
      </div>
    </button>
  );
}
export function DeviceEditor({
  unit,
  busy,
  save,
}: {
  unit: Unit;
  busy: boolean;
  save: (body: unknown) => Promise<void>;
}) {
  const [settings, setSettings] = useState({
    unit_id: unit.unit_id,
    revision: unit.revision,
    name: unit.name,
    site_id: unit.site_id,
    kind: unit.kind,
    threshold: unit.threshold,
    direction: unit.direction,
    interval_s: unit.interval_s,
    source: unit.source,
    enabled: unit.enabled,
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    void save(settings).catch(() => {});
  }
  return (
    <form onSubmit={submit} className="form-grid">
      <label className="span-two">
        Device name
        <input
          value={settings.name}
          maxLength={60}
          required
          onChange={(e) => setSettings({ ...settings, name: e.target.value })}
        />
      </label>
      <label>
        Site ID
        <input
          value={settings.site_id}
          pattern="[A-Za-z0-9_-]{1,80}"
          required
          onChange={(e) =>
            setSettings({ ...settings, site_id: e.target.value })
          }
        />
      </label>
      <label>
        Equipment
        <select
          value={settings.kind}
          onChange={(e) =>
            setSettings({ ...settings, kind: e.target.value as Unit["kind"] })
          }
        >
          <option value="fridge">Fridge</option>
          <option value="freezer">Freezer</option>
        </select>
      </label>
      <label>
        Threshold (°C)
        <input
          type="number"
          min={-90}
          max={90}
          step="0.1"
          value={settings.threshold}
          required
          onChange={(e) =>
            setSettings({ ...settings, threshold: Number(e.target.value) })
          }
        />
      </label>
      <label>
        Allowed temperatures
        <select
          value={settings.direction}
          onChange={(e) =>
            setSettings({
              ...settings,
              direction: e.target.value as Unit["direction"],
            })
          }
        >
          <option value="max">At or below threshold</option>
          <option value="min">At or above threshold</option>
        </select>
      </label>
      <label>
        Data source
        <select
          value={settings.source}
          onChange={(e) =>
            setSettings({
              ...settings,
              source: e.target.value as Unit["source"],
            })
          }
        >
          <option value="simulation">Simulated sensor</option>
          <option value="physical">Physical sensor / gateway</option>
        </select>
      </label>
      <label>
        Expected interval (seconds)
        <input
          type="number"
          min={10}
          max={300}
          value={settings.interval_s}
          required
          onChange={(e) =>
            setSettings({ ...settings, interval_s: Number(e.target.value) })
          }
        />
      </label>
      <label className="checkbox span-two">
        <input
          type="checkbox"
          checked={settings.enabled}
          onChange={(e) =>
            setSettings({ ...settings, enabled: e.target.checked })
          }
        />
        Device enabled
      </label>
      <p className="muted small span-two">
        Changing a rule resets its breach count. Stop sessions and recover open
        temperature incidents before editing. These thresholds are project
        settings.
      </p>
      <button className="button primary span-two" disabled={busy}>
        Save device settings <Check size={16} />
      </button>
    </form>
  );
}
