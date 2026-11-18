import { CheckCircle2, Clock3 } from "lucide-react";
import type { Session, Unit } from "../types";
import { Panel, Badge } from "./common";
import { live } from "../utils";

export function SimulationOutcomes({
  session,
  units,
}: {
  session: Session;
  units: Unit[];
}) {
  const target = units.find((u) => u.unit_id === session.units[0]);
  if (!target || session.mode !== "simulation") return null;
  const incidents = target.incidents.filter(
    (i) => i.opened_at >= session.started_at && i.opened_at <= session.deadline,
  );
  const offline = session.scenario === "disconnect";
  const event = incidents.find((i) =>
    offline
      ? i.kind === "sensor_offline" &&
        (i as { session_id?: string }).session_id === session.session_id
      : i.kind !== "sensor_offline",
  );
  const quiet = ["normal", "spike"].includes(session.scenario);
  const checks = quiet
    ? [{ label: "No temperature incident", observed: !event, finalOnly: true }]
    : [
        {
          label: offline
            ? "Offline incident detected"
            : "Sustained breach detected",
          observed: !!event,
          finalOnly: false,
        },
        ...(!offline
          ? [
              {
                label: "Staff notification requested",
                observed: !!event?.staff_requested,
                finalOnly: false,
              },
            ]
          : []),
        {
          label: "Fresh readings confirm recovery",
          observed: event?.status === "resolved",
          finalOnly: false,
        },
      ];
  return (
    <Panel className="outcome-panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">EXPECTED VS OBSERVED</span>
          <h2>{target.name} · scenario outcomes</h2>
        </div>
        <Badge>{live(session) ? "Observing" : "Run ended"}</Badge>
      </div>
      <div className="outcome-checks">
        {checks.map((c) => {
          const confirmed = c.observed && (!c.finalOnly || !live(session));
          return (
            <div key={c.label}>
              {confirmed ? <CheckCircle2 size={17} /> : <Clock3 size={17} />}
              <span>{c.label}</span>
              <Badge
                tone={confirmed ? "green" : live(session) ? "neutral" : "amber"}
              >
                {confirmed
                  ? "Observed"
                  : live(session)
                    ? "Waiting"
                    : "Not observed"}
              </Badge>
            </div>
          );
        })}
      </div>
      <p className="small muted">
        Based on retained incidents recorded during this session. Email delivery
        itself is not verified here. A stopped run may end before its expected
        outcome.
      </p>
    </Panel>
  );
}
