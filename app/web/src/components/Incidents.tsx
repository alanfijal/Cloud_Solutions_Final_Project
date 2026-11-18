import { useState } from "react";
import { WifiOff, Thermometer, ChevronRight, Check, Plus } from "lucide-react";
import type { Incident, Unit } from "../types";
import { Badge, Empty, Modal } from "./common";
import { TemperatureChart } from "./Chart";
import { active, title, date, time, duration } from "../utils";
export function IncidentList({
  incidents,
  units,
  select,
}: {
  incidents: Incident[];
  units: Unit[];
  select: (i: Incident) => void;
}) {
  if (!incidents.length)
    return (
      <Empty>
        No incidents here. New alerts will appear as readings arrive.
      </Empty>
    );
  return (
    <div className="incident-list">
      {incidents.map((i) => (
        <button
          className="incident-row"
          key={i.incident_id}
          onClick={() => select(i)}
        >
          <span className={`incident-icon ${active(i) ? "warn" : ""}`}>
            {i.kind === "sensor_offline" ? (
              <WifiOff size={19} />
            ) : (
              <Thermometer size={19} />
            )}
          </span>
          <span className="row-main">
            <strong>
              {units.find((u) => u.unit_id === i.unit_id)?.name || i.unit_id}
            </strong>
            <small>
              {i.kind === "sensor_offline"
                ? "Sensor offline"
                : "Temperature excursion"}{" "}
              · {date(i.opened_at)}
            </small>
          </span>
          <Badge
            tone={active(i) ? (i.acknowledged ? "blue" : "amber") : "green"}
          >
            {i.acknowledged && active(i) ? "Acknowledged" : title(i.status)}
          </Badge>
          <ChevronRight size={17} />
        </button>
      ))}
    </div>
  );
}
export function IncidentDetail({
  incident: i,
  error,
  unit,
  now,
  busy,
  close,
  mutate,
}: {
  incident: Incident;
  error: string;
  unit: Unit;
  now: number;
  busy: boolean;
  close: () => void;
  mutate: (path: string, body: unknown, message: string) => Promise<void>;
}) {
  const [action, setAction] = useState("note"),
    [text, setText] = useState("");
  const timeline = [
    {
      at: i.opened_at,
      label:
        i.kind === "sensor_offline"
          ? "Sensor silence detected"
          : "Three consecutive breaches detected",
    },
    ...(i.staff_requested
      ? [
          {
            at: i.staff_requested_at || i.opened_at,
            label: "Staff notification requested",
          },
        ]
      : []),
    ...(i.manager_requested
      ? [
          {
            at: i.escalated_at || i.opened_at + 120,
            label: "Manager escalation requested",
          },
        ]
      : []),
    ...(i.acknowledged_at
      ? [{ at: i.acknowledged_at, label: "Incident acknowledged" }]
      : []),
    ...(i.resolved_at
      ? [
          {
            at: i.resolved_at,
            label:
              i.kind === "sensor_offline"
                ? "Fresh sensor reading received"
                : "Temperature returned within range",
          },
        ]
      : []),
    ...(i.closed_at
      ? [
          {
            at: i.closed_at,
            label: "Monitoring session ended; recovery unverified",
          },
        ]
      : []),
    ...(i.activity || []).map((a) => ({
      at: a.at,
      label: `${title(a.action)}: ${a.text}`,
    })),
  ].sort((a, b) => a.at - b.at);
  return (
    <Modal label="Incident detail" wide close={close}>
      {error && (
        <div className="notice warning" role="alert">
          {error}
        </div>
      )}
      <span className="eyebrow">INCIDENT WORKSPACE</span>
      <h2>
        {unit.name} ·{" "}
        {i.kind === "sensor_offline"
          ? "Sensor offline"
          : "Temperature excursion"}
      </h2>
      <div className="incident-detail-meta">
        <Badge tone={active(i) ? "amber" : "green"}>{title(i.status)}</Badge>
        {i.acknowledged && <Badge tone="blue">Acknowledged</Badge>}
        <span className="muted small">{i.incident_id.slice(0, 12)}</span>
      </div>
      <TemperatureChart unit={unit} />
      {active(i) && !i.acknowledged && (
        <div className="incident-response">
          <div>
            <strong>
              {i.kind === "sensor_offline"
                ? "Check the sensor connection"
                : i.manager_requested
                  ? "Escalated to manager"
                  : `Escalation in ${duration(i.opened_at + 120 - now)}`}
            </strong>
            <p className="small muted">
              Acknowledgement records that someone is responding. It does not
              recover the unit.
            </p>
          </div>
          <button
            className="button primary"
            disabled={busy || now >= i.expires_at}
            onClick={() => {
              void mutate(
                "ack",
                { unit_id: i.unit_id, incident_id: i.incident_id },
                "Incident acknowledged.",
              ).catch(() => {});
            }}
          >
            <Check size={16} />
            {now >= i.expires_at ? "Acknowledgement expired" : "Acknowledge"}
          </button>
        </div>
      )}
      <div className="incident-columns">
        <div>
          <h3>Event timeline</h3>
          <ol className="timeline">
            {timeline.map((entry, index) => (
              <li key={index}>
                <span className="timeline-dot" />
                <time>{time(entry.at)}</time>
                <p>{entry.label}</p>
              </li>
            ))}
          </ol>
        </div>
        <div>
          <h3>Coordinate the response</h3>
          <p className="small muted">
            Assigned responder: <strong>{i.assignee || "Unassigned"}</strong>
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void mutate(
                "incidents",
                {
                  unit_id: i.unit_id,
                  incident_id: i.incident_id,
                  request_id: crypto.randomUUID(),
                  action,
                  text,
                },
                "Incident activity saved.",
              )
                .then(() => setText(""))
                .catch(() => {});
            }}
          >
            <label>
              Activity
              <select
                aria-label="Activity"
                value={action}
                onChange={(e) => setAction(e.target.value)}
              >
                <option value="note">Add a note</option>
                <option value="corrective">Record corrective action</option>
                <option value="assign">Assign a responder</option>
              </select>
            </label>
            <label>
              {action === "assign" ? "Responder name" : "Details"}
              <textarea
                aria-label={action === "assign" ? "Responder name" : "Details"}
                value={text}
                maxLength={action === "assign" ? 80 : 500}
                required
                onChange={(e) => setText(e.target.value)}
                placeholder={
                  action === "corrective"
                    ? "e.g. Door closed and seal checked"
                    : "Record a useful update…"
                }
              />
            </label>
            <button
              className="button secondary full"
              disabled={busy || (i.activity?.length || 0) >= 20}
            >
              <Plus size={15} />
              Save activity
            </button>
          </form>
          <p className="small muted">
            Shared operator access: names are entered by the operator and are
            not verified identities. Avoid personal or sensitive information.
          </p>
        </div>
      </div>
    </Modal>
  );
}
