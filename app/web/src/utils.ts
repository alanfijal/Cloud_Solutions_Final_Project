import type { Session, Incident, Unit } from "./types";
export const live = (s?: Session | null) =>
  !!s && ["starting", "running", "stopping"].includes(s.status);
export const active = (i: Incident) =>
  !["resolved", "closed"].includes(i.status);
export const outside = (u: Unit) =>
  u.temperature !== null &&
  (u.direction === "max"
    ? u.temperature > u.threshold
    : u.temperature < u.threshold);
export const time = (stamp?: number | null) =>
  stamp
    ? new Date(stamp * 1000).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "—";
export const date = (stamp?: number | null) =>
  stamp ? new Date(stamp * 1000).toLocaleString() : "—";
export const duration = (seconds: number) =>
  `${Math.floor(Math.max(0, seconds) / 60)}m ${Math.floor(Math.max(0, seconds) % 60)}s`;
export const title = (text: string) =>
  text.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());
