import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Unit } from "./types";
const outside = (u: Unit) =>
  u.temperature !== null &&
  (u.direction === "max"
    ? u.temperature > u.threshold
    : u.temperature < u.threshold);
export default function TemperatureChart({
  unit,
  large = false,
}: {
  unit: Unit;
  large?: boolean;
}) {
  const points = unit.history.map(([stamp, value]) => ({
    stamp: Date.parse(stamp),
    temperature: value,
  }));
  if (points.length < 2)
    return (
      <div className="empty">
        <p>Two accepted readings will reveal the temperature curve.</p>
      </div>
    );
  return (
    <div
      className={large ? "chart large" : "chart"}
      aria-label={`Temperature history for ${unit.name}`}
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart
          data={points}
          margin={{ top: 15, right: 18, left: -18, bottom: 2 }}
        >
          <CartesianGrid
            strokeDasharray="3 6"
            vertical={false}
            stroke="#e5ebe7"
          />
          <XAxis
            dataKey="stamp"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(v) =>
              new Date(v).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })
            }
            tickLine={false}
            axisLine={false}
            minTickGap={30}
            tick={{ fontSize: 11 }}
          />
          <YAxis
            domain={["auto", "auto"]}
            tickLine={false}
            axisLine={false}
            unit="°"
            tick={{ fontSize: 11 }}
          />
          <Tooltip
            labelFormatter={(v) => new Date(Number(v)).toLocaleTimeString()}
            formatter={(v) => [`${v}°C`, "Temperature"]}
          />
          <ReferenceArea
            y1={
              unit.direction === "max"
                ? unit.threshold
                : Math.min(
                    ...points.map((p) => p.temperature),
                    unit.threshold,
                  ) - 0.5
            }
            y2={
              unit.direction === "max"
                ? Math.max(
                    ...points.map((p) => p.temperature),
                    unit.threshold,
                  ) + 0.5
                : unit.threshold
            }
            fill="#e8c08b"
            fillOpacity={0.18}
            strokeOpacity={0}
            ifOverflow="extendDomain"
          />
          <ReferenceLine
            ifOverflow="extendDomain"
            y={unit.threshold}
            stroke="#c38536"
            strokeDasharray="5 5"
            label={{
              value: `Limit ${unit.threshold}°`,
              position: "insideTopRight",
              fill: "#a06b28",
              fontSize: 11,
            }}
          />
          {unit.incidents
            .filter(
              (i) =>
                i.opened_at * 1000 >= points[0].stamp &&
                i.opened_at * 1000 <= points[points.length - 1].stamp,
            )
            .map((i) => (
              <ReferenceLine
                key={i.incident_id}
                x={i.opened_at * 1000}
                stroke="#c35742"
                strokeDasharray="2 4"
              />
            ))}
          <Line
            type="linear"
            dataKey="temperature"
            stroke={outside(unit) ? "#c07b37" : "#28745c"}
            strokeWidth={2.5}
            dot={false}
            activeDot={{ r: 4 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
