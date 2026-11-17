"use strict";

const $ = (id) => document.getElementById(id);
const data = { units: [], server_time: 0, ingestion_enabled: true };
let operatorKey = "";
let filter = "all";
let refreshTimer;
let refreshDeadline = 0;
let toastTimer;
let refreshing = false;
let sending = false;
const demo = { running: false, sent: 0, started: 0, timer: null, abort: null };
const sequence = [4, 7, 4, ...Array(12).fill(7), ...Array(5).fill(4)];
const names = {
  "unit-1": "Fridge 01",
  "unit-2": "Freezer 01",
  "unit-3": "Fridge 02",
  "unit-4": "Freezer 02",
  "unit-5": "Fridge 03",
};
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const name = (u) => names[u.unit_id] || u.unit_id;
const temperature = (n) =>
  n === null || n === undefined ? "—" : Number(n).toFixed(1).replace("-", "−");
const age = (stamp) =>
  stamp
    ? Math.max(0, (Date.now() - new Date(stamp).getTime()) / 1000)
    : Infinity;
const relative = (stamp) => {
  const seconds = age(stamp);
  return !Number.isFinite(seconds)
    ? "No reading"
    : seconds < 10
      ? "Just now"
      : seconds < 60
        ? `${Math.floor(seconds)}s ago`
        : seconds < 3600
          ? `${Math.floor(seconds / 60)}m ago`
          : `${Math.floor(seconds / 3600)}h ago`;
};
const time = (stamp) =>
  new Date(stamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
const outside = (u) =>
  u.temperature != null &&
  (u.direction === "max"
    ? u.temperature > u.threshold
    : u.temperature < u.threshold);
const active = (i) => i && i.status !== "resolved";
const unitKind = (u) => (u.threshold < 0 ? "freezer" : "fridge");

function notify(message, error = false) {
  clearTimeout(toastTimer);
  $("toast").textContent = message;
  $("toast").classList.toggle("error", error);
  $("toast").hidden = false;
  toastTimer = setTimeout(() => {
    $("toast").hidden = true;
  }, 6000);
}

async function api(path, body, signal) {
  const serialized = body === undefined ? undefined : JSON.stringify(body);
  for (let attempt = 0; attempt < 3; attempt++) {
    if (signal?.aborted) throw new DOMException("Stopped", "AbortError");
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal?.addEventListener("abort", abort, { once: true });
    const timeout = setTimeout(abort, 18000);
    let retry = false;
    try {
      const result = await fetch(path, {
        method: body === undefined ? "GET" : "POST",
        headers: {
          Authorization: `Bearer ${operatorKey}`,
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        body: serialized,
        cache: "no-store",
        signal: controller.signal,
      });
      const payload = await result.json();
      if (result.ok) return payload;
      if (result.status === 401)
        throw new Error(
          "Access key rejected. Disconnect and reconnect with the current key.",
        );
      retry = result.status === 429 || result.status >= 500;
      if (!retry || attempt === 2)
        throw new Error(
          payload.error ||
            payload.message ||
            `Request failed (${result.status})`,
        );
    } catch (error) {
      if (signal?.aborted) throw new DOMException("Stopped", "AbortError");
      if (
        attempt === 2 ||
        !(error instanceof TypeError || error.name === "AbortError" || retry)
      )
        throw error;
    } finally {
      clearTimeout(timeout);
      signal?.removeEventListener("abort", abort);
    }
    await new Promise((resolve) =>
      setTimeout(resolve, 700 * 2 ** attempt + Math.random() * 400),
    );
  }
}

function status(u) {
  if (age(u.observed_at) > 90) return ["stale", "No recent reading"];
  if (active(u.incident))
    return u.incident.acknowledged
      ? ["acknowledged", "Acknowledged"]
      : [
          u.incident.status,
          u.incident.status === "escalated" ? "Escalated" : "Incident open",
        ];
  if (outside(u)) return ["warning", `Breach ${u.consecutive}/3`];
  return ["normal", "Within range"];
}

function chart(u, large = false) {
  const points = u?.history || [];
  if (!points.length)
    return large
      ? '<div class="empty"><span>∿</span>New readings will appear here.<br>Start the guided demo or send a reading.</div>'
      : '<div class="empty-chart">Waiting for new readings</div>';
  const width = large ? 900 : 280,
    height = large ? 300 : 52;
  const pad = large
    ? { x: 55, top: 25, bottom: 38 }
    : { x: 3, top: 4, bottom: 4 };
  const values = points.map((p) => Number(p[1]));
  const low = Math.min(...values, u.threshold) - 1,
    high = Math.max(...values, u.threshold) + 1;
  const y = (value) =>
    pad.top + ((high - value) / (high - low)) * (height - pad.top - pad.bottom);
  const x = (index) =>
    pad.x +
    (points.length === 1 ? 0.5 : index / (points.length - 1)) *
      (width - pad.x * 2);
  const coords = points.map(
    (p, i) => `${x(i).toFixed(1)},${y(p[1]).toFixed(1)}`,
  );
  let grid = "";
  if (large) {
    for (let i = 0; i < 4; i++) {
      const value = low + ((high - low) / 3) * i;
      grid += `<line class="grid" x1="${pad.x}" x2="${width - pad.x}" y1="${y(value)}" y2="${y(value)}"/><text x="12" y="${y(value) + 4}">${temperature(value)}°</text>`;
    }
    grid += `<text x="${pad.x}" y="${height - 10}">${esc(time(points[0][0]))}</text><text text-anchor="end" x="${width - pad.x}" y="${height - 10}">${esc(time(points.at(-1)[0]))}</text>`;
  }
  return `<svg class="${large ? "large-chart" : "sparkline"}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(name(u))} temperature history, ${points.length} readings">
    ${grid}<line class="threshold" x1="${pad.x}" x2="${width - pad.x}" y1="${y(u.threshold)}" y2="${y(u.threshold)}"/>
    <polygon class="area" points="${x(0)},${height - pad.bottom} ${coords.join(" ")} ${x(points.length - 1)},${height - pad.bottom}"/>
    <polyline class="line" points="${coords.join(" ")}"/><circle class="last-point" cx="${x(points.length - 1)}" cy="${y(points.at(-1)[1])}" r="3"/>
  </svg>`;
}

function incidents() {
  return data.units
    .flatMap((u) => (u.incidents || []).map((i) => ({ ...i, unit: u })))
    .sort((a, b) => b.opened_at - a.opened_at);
}

function incidentRows(items) {
  if (!items.length)
    return '<div class="empty"><span>✓</span>All quiet here.<br>Incidents will appear after three consecutive breaches.</div>';
  return items
    .map((i) => {
      const acknowledged = i.acknowledged && i.status !== "resolved";
      const label =
        i.status === "resolved"
          ? "Recovered"
          : acknowledged
            ? "Acknowledged"
            : i.status === "escalated"
              ? "Escalated"
              : "Open";
      const canAck =
        active(i) && !i.acknowledged && i.expires_at > Date.now() / 1000;
      return `<div class="incident-row"><div class="incident-info"><span class="incident-symbol ${esc(i.status)}">${i.status === "resolved" ? "✓" : "!"}</span><div><div class="incident-name">${esc(name(i.unit))} · Temperature breach</div><div class="incident-meta">${esc(new Date(i.opened_at * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }))} · ${esc(i.incident_id.slice(0, 8))}</div></div></div><div class="incident-actions"><span class="badge ${acknowledged ? "acknowledged" : esc(i.status)}">${label}</span>${canAck ? `<button class="button secondary" data-ack="${esc(i.incident_id)}" data-unit="${esc(i.unit_id)}">Acknowledge</button>` : ""}</div></div>`;
    })
    .join("");
}

function render() {
  $("stat-units").textContent = data.units.length;
  $("stat-normal").textContent = data.units.filter(
    (u) => age(u.observed_at) <= 90 && u.temperature != null && !outside(u),
  ).length;
  const ongoing = data.units.filter((u) => active(u.incident));
  $("stat-incidents").textContent = ongoing.length;
  $("stat-incident-detail").textContent = ongoing.length
    ? `${ongoing.filter((u) => !u.incident.acknowledged).length} awaiting acknowledgement`
    : "No active incidents";
  $("stat-reporting").textContent = data.units.filter(
    (u) => age(u.observed_at) <= 90,
  ).length;
  $("nav-incident-count").textContent = ongoing.length;
  const selected = data.units.filter(
    (u) => filter === "all" || unitKind(u) === filter,
  );
  $("unit-total").textContent = selected.length;
  $("unit-grid").innerHTML = selected
    .map((u) => {
      const [kind, label] = status(u);
      return `<button class="unit-card ${kind === "open" || kind === "escalated" ? "alert" : kind}" data-chart="${esc(u.unit_id)}" aria-label="View ${esc(name(u))} temperature history"><div class="unit-top"><span class="unit-type"><span class="unit-symbol ${unitKind(u)}">${unitKind(u) === "freezer" ? "❄" : "▤"}</span>${esc(name(u))}</span><span class="badge ${kind}">${label}</span></div><div class="temperature-line"><strong class="temperature">${temperature(u.temperature)}<small> °C</small></strong><span class="temperature-label">${u.direction === "max" ? "Max" : "Min"} ${temperature(u.threshold)}°C</span></div>${chart(u)}<div class="unit-bottom"><span>${esc(u.unit_id)} · ${esc(u.site_id)}</span><span>${esc(relative(u.observed_at))}</span></div></button>`;
    })
    .join("");
  const all = incidents();
  $("overview-incidents").innerHTML = incidentRows(all.slice(0, 3));
  $("all-incidents").innerHTML = incidentRows(all);
  for (const id of ["manual-unit", "history-unit"]) {
    const before = $(id).value;
    $(id).innerHTML = data.units
      .map((u) => `<option value="${esc(u.unit_id)}">${esc(name(u))}</option>`)
      .join("");
    if (data.units.some((u) => u.unit_id === before)) $(id).value = before;
  }
  renderHistory();
  $("start-demo").disabled = !data.ingestion_enabled || sending;
  $("send-reading").disabled =
    !data.ingestion_enabled || demo.running || sending;
}

function renderHistory() {
  const u = data.units.find((unit) => unit.unit_id === $("history-unit").value);
  if (!u) {
    $("large-chart").replaceChildren();
    $("history-summary").replaceChildren();
    $("export-history").disabled = true;
    return;
  }
  $("large-chart").innerHTML = chart(u, true);
  const values = u.history.map((p) => p[1]);
  $("history-summary").innerHTML =
    `<div><small>Latest</small><strong>${temperature(u.temperature)}°C</strong></div><div><small>Minimum</small><strong>${values.length ? temperature(Math.min(...values)) : "—"}°C</strong></div><div><small>Maximum</small><strong>${values.length ? temperature(Math.max(...values)) : "—"}°C</strong></div><div><small>Readings</small><strong>${values.length}</strong></div>`;
  $("export-history").disabled = !values.length;
}

async function refresh() {
  if (refreshing || !operatorKey) return;
  const connectedKey = operatorKey;
  refreshing = true;
  $("refresh").disabled = true;
  try {
    const snapshot = await api("/dashboard/state");
    if (!operatorKey || operatorKey !== connectedKey) return;
    Object.assign(data, snapshot);
    render();
    $("connection").classList.add("connected");
    $("connection").lastChild.textContent = "Connected";
    $("last-sync").textContent = `Updated ${time(Date.now())}`;
  } finally {
    refreshing = false;
    $("refresh").disabled = false;
  }
}

function scheduleRefresh() {
  clearTimeout(refreshTimer);
  if (!operatorKey) return;
  if (Date.now() >= refreshDeadline) {
    $("auto-refresh-status").textContent =
      "Auto-refresh paused · press Refresh to resume";
    return;
  }
  $("auto-refresh-status").textContent =
    "Updates every 10s · pauses after 10 minutes";
  refreshTimer = setTimeout(async () => {
    try {
      await refresh();
    } catch (e) {
      notify(e.message, true);
    }
    scheduleRefresh();
  }, 10000);
}

function view(which) {
  for (const section of document.querySelectorAll(".view"))
    section.hidden = section.id !== `${which}-view`;
  for (const button of document.querySelectorAll(".nav-item"))
    button.classList.toggle("active", button.dataset.view === which);
  const content = {
    overview: [
      "Overview",
      "Cold-chain overview",
      "A clear view of your units, temperatures and incidents.",
    ],
    incidents: [
      "Incidents",
      "Respond with confidence.",
      "Track alerts, acknowledge incidents and follow recovery.",
    ],
    history: [
      "Temperature history",
      "Follow every degree.",
      "Explore the recent readings behind each unit’s current state.",
    ],
  }[which];
  $("view-label").textContent = content[0];
  $("page-title").textContent = content[1];
  $("page-description").textContent = content[2];
}

function reading(u, value) {
  return {
    reading_id: crypto.randomUUID().replaceAll("-", ""),
    unit_id: u.unit_id,
    site_id: u.site_id,
    observed_at: new Date().toISOString(),
    temperature: value,
    schema_version: 1,
  };
}

function stopDemo(
  message = "Simulation stopped. Accepted readings remain in history.",
  error = false,
) {
  demo.running = false;
  clearTimeout(demo.timer);
  demo.abort?.abort();
  $("start-demo").hidden = false;
  $("stop-demo").hidden = true;
  $("send-reading").disabled = !data.ingestion_enabled || sending;
  for (const control of document.querySelectorAll(
    ".reading-controls input,.reading-controls select,.reading-controls button",
  ))
    control.disabled = !data.ingestion_enabled;
  if (message) notify(message, error);
}

function demoStep() {
  if (!demo.running) return;
  if (demo.sent >= 100 || Date.now() - demo.started >= 600000) {
    stopDemo(
      `Demo complete: ${demo.sent} readings sent. No simulation is running.`,
    );
    return;
  }
  const due = demo.started + demo.sent * 6000;
  demo.timer = setTimeout(
    async () => {
      if (!demo.running || Date.now() - demo.started >= 600000) {
        stopDemo("The 10-minute simulation limit was reached.");
        return;
      }
      const u = data.units[demo.sent % data.units.length];
      const round = Math.floor(demo.sent / data.units.length);
      const normal = u.direction === "max" ? u.threshold - 2 : u.threshold + 2;
      const value =
        u.unit_id === "unit-1" ? sequence[Math.min(round, 19)] : normal;
      try {
        await api("/dashboard/readings", reading(u, value), demo.abort.signal);
        if (!demo.running) return;
        demo.sent++;
        $("demo-count").textContent = `${demo.sent} / 100`;
        $("progress").value = demo.sent;
        $("demo-phase").textContent =
          round === 0
            ? "Normal readings"
            : round === 1
              ? "Single spike · no incident expected"
              : round === 2
                ? "Back in range · counter resets"
                : round < 5
                  ? "Sustained warming · counting breaches"
                  : round < 9
                    ? "Incident open · staff notification"
                    : round < 15
                      ? "Escalation window · acknowledgement available"
                      : "Recovery · returning to normal";
        demoStep();
      } catch (e) {
        if (demo.running) stopDemo(`Simulation stopped: ${e.message}`, true);
      }
    },
    Math.max(0, due - Date.now()),
  );
}

$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  operatorKey = $("access-key").value.trim();
  $("connect").disabled = true;
  $("login-error").textContent = "";
  try {
    await refresh();
    $("login").close();
    $("access-key").value = "";
    refreshDeadline = Date.now() + 600000;
    scheduleRefresh();
  } catch (e) {
    operatorKey = "";
    $("login-error").textContent = e.message;
  } finally {
    $("connect").disabled = false;
  }
});
$("disconnect").addEventListener("click", () => {
  stopDemo("");
  clearTimeout(refreshTimer);
  operatorKey = "";
  data.units = [];
  render();
  $("connection").classList.remove("connected");
  $("connection").lastChild.textContent = "Disconnected";
  $("login").showModal();
});
$("refresh").addEventListener("click", async () => {
  try {
    await refresh();
    refreshDeadline = Date.now() + 600000;
    scheduleRefresh();
  } catch (e) {
    notify(e.message, true);
  }
});
document.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  if (button.dataset.view) view(button.dataset.view);
  if (button.dataset.filter) {
    filter = button.dataset.filter;
    document
      .querySelectorAll(".filter")
      .forEach((b) => b.classList.toggle("active", b === button));
    render();
  }
  if (button.dataset.chart) {
    $("history-unit").value = button.dataset.chart;
    renderHistory();
    view("history");
  }
  if (button.dataset.ack) {
    button.disabled = true;
    try {
      await api("/dashboard/ack", {
        unit_id: button.dataset.unit,
        incident_id: button.dataset.ack,
      });
      notify("Incident acknowledged. Temperature monitoring continues.");
      await refresh();
    } catch (e) {
      notify(e.message, true);
      button.disabled = false;
    }
  }
});
$("history-unit").addEventListener("change", renderHistory);
$("normal-temperature").addEventListener("click", () => {
  const u = data.units.find((u) => u.unit_id === $("manual-unit").value);
  $("manual-temperature").value =
    u.direction === "max" ? u.threshold - 2 : u.threshold + 2;
});
$("breach-temperature").addEventListener("click", () => {
  const u = data.units.find((u) => u.unit_id === $("manual-unit").value);
  $("manual-temperature").value =
    u.direction === "max" ? u.threshold + 2 : u.threshold - 2;
});
$("reading-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (demo.running || sending) return;
  const u = data.units.find((u) => u.unit_id === $("manual-unit").value);
  const value = Number($("manual-temperature").value);
  if (!u || !Number.isFinite(value) || value < -100 || value > 100) return;
  sending = true;
  $("send-reading").disabled = true;
  $("start-demo").disabled = true;
  try {
    await api("/dashboard/readings", reading(u, value));
    $("manual-status").textContent =
      `${temperature(value)}°C accepted for ${name(u)}. The status will update after processing.`;
    notify(`Reading accepted for ${name(u)}.`);
  } catch (e) {
    notify(e.message, true);
  } finally {
    sending = false;
    $("send-reading").disabled = !data.ingestion_enabled;
    $("start-demo").disabled = !data.ingestion_enabled;
  }
});
$("start-demo").addEventListener("click", () => {
  if (demo.running || sending || !data.units.length) return;
  demo.running = true;
  demo.sent = 0;
  demo.started = Date.now();
  demo.abort = new AbortController();
  $("start-demo").hidden = true;
  $("stop-demo").hidden = false;
  $("demo-progress").hidden = false;
  $("demo-count").textContent = "0 / 100";
  $("progress").value = 0;
  for (const control of document.querySelectorAll(
    ".reading-controls input,.reading-controls select,.reading-controls button",
  ))
    control.disabled = true;
  refreshDeadline = demo.started + 600000;
  scheduleRefresh();
  notify("Guided demo started. Keep this tab open; stop at any time.");
  demoStep();
});
$("stop-demo").addEventListener("click", () => stopDemo());
$("export-history").addEventListener("click", () => {
  const u = data.units.find((u) => u.unit_id === $("history-unit").value);
  if (!u) return;
  const rows = [
    "unit_id,observed_at,temperature_c",
    ...u.history.map((p) => `${u.unit_id},${p[0]},${p[1]}`),
  ];
  const url = URL.createObjectURL(
    new Blob([rows.join("\n") + "\n"], { type: "text/csv;charset=utf-8" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = `${u.unit_id}-temperature.csv`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
window.addEventListener("pagehide", () => {
  stopDemo("");
  clearTimeout(refreshTimer);
  operatorKey = "";
});
$("login").addEventListener("cancel", (event) => event.preventDefault());
$("login").close();
$("login").showModal();
