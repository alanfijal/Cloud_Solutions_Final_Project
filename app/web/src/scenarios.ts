import {
  Thermometer,
  Snowflake,
  Activity,
  ChartNoAxesCombined,
  WifiOff,
  ShieldCheck,
} from "lucide-react";
export const SCENARIOS = [
  [
    "door_open",
    "Door left open",
    "Temperature rises, stays above the limit, then cools after the door closes.",
    Thermometer,
  ],
  [
    "compressor",
    "Compressor failure",
    "A sustained failure tests detection, staff notification and escalation.",
    Snowflake,
  ],
  [
    "spike",
    "Brief spike",
    "A single high reading should pass without opening an incident.",
    Activity,
  ],
  [
    "warming",
    "Gradual warming",
    "A progressive rise tests the threshold as conditions deteriorate.",
    ChartNoAxesCombined,
  ],
  [
    "disconnect",
    "Sensor disconnected",
    "Readings stop, an offline alert opens, then fresh data restores contact.",
    WifiOff,
  ],
  [
    "normal",
    "Normal operation",
    "A stable baseline with small, deterministic temperature variations.",
    ShieldCheck,
  ],
] as const;
