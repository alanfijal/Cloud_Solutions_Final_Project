import { lazy, Suspense } from "react";
import type { Unit } from "../types";
import { Empty } from "./common";
const LazyChart = lazy(() => import("../TemperatureChart"));
export function TemperatureChart(props: { unit: Unit; large?: boolean }) {
  return (
    <Suspense fallback={<Empty>Loading chart…</Empty>}>
      <LazyChart {...props} />
    </Suspense>
  );
}
