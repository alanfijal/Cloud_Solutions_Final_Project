import { useState } from "react";
import { ChartNoAxesCombined, ArrowDownToLine } from "lucide-react";
import type { Unit, Report } from "../types";
import { Panel, Badge, Empty } from "../components/common";
import { csv } from "../api";
import { title, date, duration } from "../utils";
export function Analytics({
  units,
  report,
  busy,
  generate,
}: {
  units: Unit[];
  report: Report | null;
  busy: boolean;
  generate: (body: unknown) => Promise<void>;
}) {
  const [window, setWindow] = useState("24h"),
    [unit, setUnit] = useState("all");
  const selectedUnit = units.some((u) => u.unit_id === unit) ? unit : "all";
  const rows = report?.rows || [];
  const total = rows.reduce((sum, r) => sum + Number(r.readings || 0), 0);
  function exportReport() {
    if (!rows.length) return;
    const columns = Object.keys(rows[0]);
    csv("coldchain-report.csv", [
      columns,
      ...rows.map((row) => columns.map((key) => row[key])),
    ]);
  }
  return (
    <>
      <Panel className="report-controls">
        <div>
          <span className="eyebrow">FROM THE EVENT HISTORY</span>
          <h2>A clearer picture of your cold chain.</h2>
          <p className="muted">
            Generate a report when you need it. Historical results include data
            gaps and response times.
          </p>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void generate({
              request_id: crypto.randomUUID(),
              units:
                selectedUnit === "all"
                  ? units.map((u) => u.unit_id)
                  : [selectedUnit],
              window,
            }).catch(() => {});
          }}
        >
          <label>
            Devices
            <select
              value={selectedUnit}
              onChange={(e) => setUnit(e.target.value)}
            >
              <option value="all">All devices</option>
              {units.map((u) => (
                <option key={u.unit_id} value={u.unit_id}>
                  {u.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Time window
            <select value={window} onChange={(e) => setWindow(e.target.value)}>
              <option value="1h">Last hour</option>
              <option value="24h">Last 24 hours</option>
              <option value="7d">Last 7 days</option>
            </select>
          </label>
          <button
            className="button primary"
            disabled={
              busy ||
              (!!report && ["queued", "running"].includes(report.status))
            }
          >
            <ChartNoAxesCombined size={16} />
            Generate report
          </button>
        </form>
      </Panel>
      {report && (
        <div className="report-meta">
          <Badge
            tone={
              report.status === "succeeded"
                ? "green"
                : report.status === "failed" || report.status === "cancelled"
                  ? "amber"
                  : "blue"
            }
          >
            {title(report.status)}
          </Badge>
          <span>
            {date(report.start)} → {date(report.end)}
          </span>
        </div>
      )}
      {report?.error && <div className="notice warning">{report.error}</div>}
      {report?.status === "succeeded" ? (
        <>
          <div className="stats-grid three">
            <Panel>
              <span className="stat-label">Recorded readings</span>
              <strong className="stat-value">{total.toLocaleString()}</strong>
              <small>In the selected period</small>
            </Panel>
            <Panel>
              <span className="stat-label">Incidents opened</span>
              <strong className="stat-value">
                {rows.reduce((s, r) => s + Number(r.incidents || 0), 0)}
              </strong>
              <small>Temperature and connectivity incidents</small>
            </Panel>
            <Panel>
              <span className="stat-label">Report coverage</span>
              <strong className="stat-value">
                {rows.length} <span>devices</span>
              </strong>
              <small>Devices with history in this window</small>
            </Panel>
          </div>
          <Panel>
            <div className="panel-heading">
              <h2>Temperature & response report</h2>
              <button
                className="button secondary"
                disabled={!rows.length}
                onClick={exportReport}
              >
                <ArrowDownToLine size={16} />
                Export CSV
              </button>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Device</th>
                    <th>Readings</th>
                    <th>Min / max</th>
                    <th>Observed time</th>
                    <th>Outside limit</th>
                    <th>Unknown time</th>
                    <th>Avg. response</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.unit_id}>
                      <td>
                        <strong>
                          {units.find((u) => u.unit_id === r.unit_id)?.name ||
                            r.unit_id}
                        </strong>
                      </td>
                      <td>{r.readings}</td>
                      <td>
                        {r.minimum === null
                          ? "—"
                          : `${Number(r.minimum).toFixed(1)} / ${Number(r.maximum).toFixed(1)}°C`}
                      </td>
                      <td>{duration(Number(r.observed_seconds || 0))}</td>
                      <td>{duration(Number(r.excursion_seconds || 0))}</td>
                      <td>
                        {duration(
                          Math.max(
                            0,
                            report.end -
                              report.start -
                              Number(r.observed_seconds || 0),
                          ),
                        )}
                      </td>
                      <td>
                        {r.response_seconds === null
                          ? "—"
                          : duration(Number(r.response_seconds))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!rows.length && (
              <Empty>
                No readings for this period. Choose another time window or
                collect more readings.
              </Empty>
            )}
          </Panel>
          <p className="panel-footnote">
            Durations are estimates between readings. Gaps without enough data
            appear as unknown.
          </p>
        </>
      ) : (
        !report && (
          <Panel>
            <Empty>
              Choose your time window and generate the first historical report.
            </Empty>
          </Panel>
        )
      )}
    </>
  );
}
