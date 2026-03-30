const POLL_INTERVAL_IDLE_MS = 15000;
const POLL_INTERVAL_ACTIVE_MS = 3000;
const FULL_REFRESH_INTERVAL_IDLE_MS = 45000;
const FULL_REFRESH_INTERVAL_ACTIVE_MS = 9000;
const BACKUP_REQUEST_TIMEOUT_MS = 5000;

const state = {
  config: null,
  status: null,
  runtime: null,
  logs: [],
  lastUpdated: {
    status: null,
    logs: null,
    runtime: null,
  },
  sync: {
    runtime: "idle",
    status: "idle",
    logs: "idle",
  },
  requestIds: {
    runtime: 0,
    status: 0,
    logs: 0,
  },
  pollHandle: null,
  lastFullRefreshAt: 0,
};

async function api(path, options = {}) {
  const { timeoutMs = 30000, headers = {}, ...fetchOptions } = options;
  const controller = new AbortController();
  const timeoutHandle = window.setTimeout(() => controller.abort(), timeoutMs);
  let response;
  let text;
  try {
    response = await fetch(path, {
      ...fetchOptions,
      headers: {
        ...(fetchOptions.body ? { "Content-Type": "application/json" } : {}),
        ...headers,
      },
      signal: controller.signal,
    });
    text = await response.text();
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("Request timed out");
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutHandle);
  }
  let payload;
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(`HTTP ${response.status}: ${text.slice(0, 160) || "non-JSON response"}`);
  }
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.message || "Request failed");
  }
  return payload;
}

function flash(message, type = "info") {
  const node = document.getElementById("flash");
  node.textContent = message;
  node.className = `flash ${type === "error" ? "error" : ""}`;
}

function formatTimestamp(value) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function hasActiveRun() {
  return Boolean(state.runtime?.current_run || state.status?.current_run);
}

function setSyncState(key, nextState) {
  state.sync[key] = nextState;
  renderSyncState();
}

function renderSyncState() {
  const node = document.getElementById("sync-status");
  const detail = document.getElementById("sync-updated");
  const currentStates = Object.values(state.sync);

  if (currentStates.includes("error")) {
    node.textContent = "Sync degraded";
    node.className = "sync-pill sync-error";
  } else if (hasActiveRun() || currentStates.includes("loading")) {
    node.textContent = hasActiveRun() ? "Live monitoring" : "Syncing";
    node.className = "sync-pill sync-active";
  } else {
    node.textContent = "In sync";
    node.className = "sync-pill";
  }

  const latestTimestamp = [state.lastUpdated.runtime, state.lastUpdated.status, state.lastUpdated.logs]
    .filter(Boolean)
    .sort()
    .at(-1);
  detail.textContent = latestTimestamp
    ? `Last update: ${formatTimestamp(latestTimestamp)}`
    : "The dashboard is connecting to the backend.";
}

function renderRunIndicator() {
  const node = document.getElementById("run-indicator");
  const currentRun = state.runtime?.current_run || state.status?.current_run;
  if (!currentRun) {
    node.textContent = "";
    node.className = "run-indicator hidden";
    return;
  }
  const actionLabel = currentRun.action[0].toUpperCase() + currentRun.action.slice(1);
  const startedAt = formatTimestamp(currentRun.started_at);
  const tag = currentRun.tag ? ` Tag: ${currentRun.tag}.` : "";
  node.textContent = `${actionLabel} running now.${tag} Started at ${startedAt}.`;
  node.className = "run-indicator";
}

function switchView(nextView) {
  document.querySelectorAll("[data-panel]").forEach((panel) => {
    panel.classList.toggle("visible", panel.dataset.panel === nextView);
  });
  document.querySelectorAll(".sidebar button[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === nextView);
  });
  document.getElementById("view-title").textContent = nextView[0].toUpperCase() + nextView.slice(1);
}

function readConfigFromForm() {
  const config = structuredClone(state.config);
  config.provider.type = document.getElementById("provider-type").value.trim();
  config.provider.remote_name = document.getElementById("remote-name").value.trim();
  config.provider.repository = document.getElementById("repository").value.trim();
  config.provider.restic_password = document.getElementById("restic-password").value;
  config.provider.rclone_config = document.getElementById("rclone-config").value;
  config.general.authorized_roots = document.getElementById("authorized-roots").value.split("\n").map((line) => line.trim()).filter(Boolean);
  config.exclusions = document.getElementById("exclusions").value.split("\n").map((line) => line.trim()).filter(Boolean);
  config.retention.keep_last = Number(document.getElementById("keep-last").value);
  config.retention.keep_daily = Number(document.getElementById("keep-daily").value);
  config.retention.keep_weekly = Number(document.getElementById("keep-weekly").value);
  config.retention.keep_monthly = Number(document.getElementById("keep-monthly").value);
  config.sources = Array.from(document.querySelectorAll(".source-row")).map((row) => ({
    path: row.querySelector("[data-source-path]").value.trim(),
    enabled: row.querySelector("[data-source-enabled]").checked,
    allow_empty: row.querySelector("[data-source-empty]").checked,
  }));
  ["backup", "forget", "prune"].forEach((jobName) => {
    const row = document.querySelector(`[data-job="${jobName}"]`);
    config.schedule[jobName] = {
      enabled: row.querySelector("[data-job-enabled]").checked,
      time: row.querySelector("[data-job-time]").value,
      days_of_week: row.querySelector("[data-job-days]").value
        .split(",")
        .map((value) => Number(value.trim()))
        .filter((value) => !Number.isNaN(value)),
    };
  });
  return config;
}

function renderSources() {
  const root = document.getElementById("source-list");
  root.innerHTML = "";
  state.config.sources.forEach((source) => {
    const wrapper = document.createElement("div");
    wrapper.className = "source-row";
    wrapper.innerHTML = `
      <label>Path <input data-source-path value="${source.path}"></label>
      <label><input type="checkbox" data-source-enabled ${source.enabled ? "checked" : ""}> Enabled</label>
      <label><input type="checkbox" data-source-empty ${source.allow_empty ? "checked" : ""}> Allow empty</label>
    `;
    root.appendChild(wrapper);
  });
}

function renderSchedule() {
  const root = document.getElementById("schedule-form");
  root.innerHTML = "";
  ["backup", "forget", "prune"].forEach((jobName) => {
    const job = state.config.schedule[jobName];
    const wrapper = document.createElement("div");
    wrapper.className = "card";
    wrapper.dataset.job = jobName;
    wrapper.innerHTML = `
      <h4>${jobName}</h4>
      <label><input type="checkbox" data-job-enabled ${job.enabled ? "checked" : ""}> Enabled</label>
      <label>Time <input data-job-time value="${job.time}"></label>
      <label>Days of week (0=Mon ... 6=Sun) <input data-job-days value="${job.days_of_week.join(",")}"></label>
    `;
    root.appendChild(wrapper);
  });
}

function renderConfig() {
  const { provider, general, retention } = state.config;
  document.getElementById("provider-type").value = provider.type;
  document.getElementById("remote-name").value = provider.remote_name;
  document.getElementById("repository").value = provider.repository;
  document.getElementById("restic-password").value = provider.restic_password;
  document.getElementById("rclone-config").value = provider.rclone_config || "";
  document.getElementById("authorized-roots").value = general.authorized_roots.join("\n");
  document.getElementById("exclusions").value = state.config.exclusions.join("\n");
  document.getElementById("keep-last").value = retention.keep_last;
  document.getElementById("keep-daily").value = retention.keep_daily;
  document.getElementById("keep-weekly").value = retention.keep_weekly;
  document.getElementById("keep-monthly").value = retention.keep_monthly;
  renderSources();
  renderSchedule();
}

function renderStatus() {
  const payload = state.status;
  if (!payload) {
    return;
  }

  const currentRun = state.runtime?.current_run || payload.current_run;
  renderRunIndicator();
  document.getElementById("status-gate").textContent = payload.preflight?.ok ? "PASS" : "BLOCKED";
  document.getElementById("status-failures").textContent = (payload.preflight?.failures || []).join("\n") || "No blocking failures.";
  document.getElementById("snapshot-count").textContent = String((payload.snapshots || []).length);
  document.getElementById("last-backup").textContent = state.runtime?.last_successful_backup || payload.last_successful_backup || "No successful backup yet.";
  document.getElementById("repo-usage").textContent = payload.stats?.total_size || "N/A";
  document.getElementById("repo-files").textContent = JSON.stringify(payload.stats || {}, null, 2);
  const runButton = document.getElementById("run-backup");
  if (currentRun?.action === "backup") {
    runButton.disabled = true;
    runButton.textContent = "Backup running...";
  } else {
    runButton.disabled = false;
    runButton.textContent = "Run backup";
  }
  const preflightList = document.getElementById("preflight-list");
  preflightList.innerHTML = "";
  (payload.preflight?.source_results || []).forEach((entry) => {
    const li = document.createElement("li");
    li.textContent = `${entry.path}: exists=${entry.exists} readable=${entry.readable} non_empty=${entry.non_empty}`;
    preflightList.appendChild(li);
  });
  document.getElementById("restore-snapshots").textContent = JSON.stringify(payload.snapshots || [], null, 2);
}

function renderLogs() {
  const output = document.getElementById("logs-output");
  if (!state.logs.length) {
    output.textContent = "No operations logged yet.";
    return;
  }

  output.textContent = state.logs
    .slice()
    .reverse()
    .map((entry) => {
      const timestamp = formatTimestamp(entry.timestamp);
      const action = entry.action || entry.phase || "event";
      const status = entry.ok === true ? "OK" : entry.ok === false ? "ERROR" : "INFO";
      const summary = entry.message || entry.tag || entry.snapshot_id || "";
      return [timestamp, status, action, summary].filter(Boolean).join(" | ");
    })
    .join("\n");
}

async function loadConfig() {
  const payload = await api("/api/config");
  state.config = payload.config;
  renderConfig();
}

async function loadRuntime() {
  const requestId = ++state.requestIds.runtime;
  setSyncState("runtime", "loading");
  try {
    const payload = await api("/api/runtime", { timeoutMs: 10000 });
    if (requestId !== state.requestIds.runtime) {
      return;
    }
    state.runtime = payload;
    state.lastUpdated.runtime = payload.timestamp;
    setSyncState("runtime", "idle");
    renderStatus();
  } catch (error) {
    if (requestId === state.requestIds.runtime) {
      setSyncState("runtime", "error");
    }
    throw error;
  }
}

async function loadStatus() {
  const requestId = ++state.requestIds.status;
  setSyncState("status", "loading");
  try {
    const payload = await api("/api/status", { timeoutMs: 30000 });
    if (requestId !== state.requestIds.status) {
      return;
    }
    state.status = payload;
    state.lastUpdated.status = payload.timestamp;
    state.lastFullRefreshAt = Date.now();
    setSyncState("status", "idle");
    renderStatus();
  } catch (error) {
    if (requestId === state.requestIds.status) {
      setSyncState("status", "error");
    }
    throw error;
  }
}

async function loadLogs() {
  const requestId = ++state.requestIds.logs;
  setSyncState("logs", "loading");
  try {
    const payload = await api("/api/logs", { timeoutMs: 15000 });
    if (requestId !== state.requestIds.logs) {
      return;
    }
    state.logs = payload.operations || [];
    state.lastUpdated.logs = payload.timestamp;
    setSyncState("logs", "idle");
    renderLogs();
  } catch (error) {
    if (requestId === state.requestIds.logs) {
      setSyncState("logs", "error");
    }
    throw error;
  }
}

async function loadAll({ includeConfig = true } = {}) {
  const tasks = [
    loadRuntime(),
    loadStatus(),
    loadLogs(),
  ];
  if (includeConfig) {
    tasks.push(loadConfig());
  }
  const results = await Promise.allSettled(tasks);
  if (results.every((result) => result.status === "rejected")) {
    throw results[0].reason;
  }
}

async function refreshStatus() {
  await Promise.allSettled([loadRuntime(), loadStatus()]);
}

function shouldRunFullRefresh() {
  const interval = hasActiveRun() ? FULL_REFRESH_INTERVAL_ACTIVE_MS : FULL_REFRESH_INTERVAL_IDLE_MS;
  return Date.now() - state.lastFullRefreshAt >= interval;
}

function schedulePolling() {
  window.clearTimeout(state.pollHandle);
  state.pollHandle = window.setTimeout(async () => {
    try {
      await loadRuntime();
      if (shouldRunFullRefresh()) {
        await Promise.allSettled([loadStatus(), loadLogs()]);
      }
    } finally {
      schedulePolling();
    }
  }, hasActiveRun() ? POLL_INTERVAL_ACTIVE_MS : POLL_INTERVAL_IDLE_MS);
}

function applyOptimisticBackupState(tag) {
  state.runtime = {
    ok: true,
    timestamp: new Date().toISOString(),
    current_run: {
      action: "backup",
      started_at: new Date().toISOString(),
      tag,
    },
    last_successful_backup: state.runtime?.last_successful_backup || state.status?.last_successful_backup || null,
  };
  renderStatus();
}

document.addEventListener("DOMContentLoaded", async () => {
  document.querySelectorAll(".sidebar button[data-view]").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.view));
  });

  document.getElementById("reload-status").addEventListener("click", async () => {
    await loadAll({ includeConfig: false });
    flash("Status reloaded.");
  });

  document.getElementById("run-preflight").addEventListener("click", async () => {
    const payload = await api("/api/preflight");
    flash(payload.ok ? "Preflight passed." : `Preflight blocked: ${payload.failures.join(", ")}`, payload.ok ? "info" : "error");
    await refreshStatus();
  });

  document.getElementById("run-backup").addEventListener("click", async () => {
    if (hasActiveRun() && (state.runtime?.current_run || state.status?.current_run)?.action === "backup") {
      flash("A backup is already running.", "error");
      return;
    }
    const button = document.getElementById("run-backup");
    const originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = "Backup running...";
    flash("Backup request sent. The first run can take a long time to finish.", "info");
    applyOptimisticBackupState("manual-web");
    schedulePolling();
    try {
      const payload = await api("/api/actions/backup", {
        method: "POST",
        body: JSON.stringify({ tag: "manual-web" }),
        timeoutMs: BACKUP_REQUEST_TIMEOUT_MS,
      });
      flash(payload.ok ? "Backup completed successfully." : "Backup failed.", payload.ok ? "info" : "error");
      await loadAll({ includeConfig: false });
    } catch (error) {
      try {
        await loadRuntime();
        await Promise.allSettled([loadStatus(), loadLogs()]);
      } catch {
        // Ignore status refresh failures and fall back to the original error.
      }
      const currentRun = state.runtime?.current_run || state.status?.current_run;
      if (currentRun?.action === "backup") {
        flash("Backup is still running on the server. The web request timed out while waiting for completion.", "info");
      } else {
        flash(`Backup failed to start: ${error.message}`, "error");
      }
    } finally {
      const activeRun = state.runtime?.current_run || state.status?.current_run;
      if (activeRun?.action !== "backup") {
        button.disabled = false;
        button.textContent = originalLabel;
      }
    }
  });

  document.getElementById("save-config").addEventListener("click", async () => {
    state.config = readConfigFromForm();
    const payload = await api("/api/config", { method: "PUT", body: JSON.stringify({ config: state.config }) });
    state.config = payload.config;
    renderConfig();
    flash("Configuration saved.");
  });

  document.getElementById("validate-config").addEventListener("click", async () => {
    const config = readConfigFromForm();
    await api("/api/config/validate", { method: "POST", body: JSON.stringify({ config }) });
    flash("Configuration is valid.");
  });

  document.getElementById("add-source").addEventListener("click", () => {
    state.config.sources.push({ path: state.config.general.authorized_roots[0] || "/source/raid1", enabled: true, allow_empty: false });
    renderSources();
  });

  document.getElementById("browse-root").addEventListener("click", async () => {
    const path = state.config.general.authorized_roots[0];
    const payload = await api(`/api/browse?path=${encodeURIComponent(path)}`);
    flash(`Found ${payload.entries.length} directories under ${payload.path}.`);
  });

  document.getElementById("run-restore").addEventListener("click", async () => {
    const payload = await api("/api/actions/restore", {
      method: "POST",
      body: JSON.stringify({
        snapshot_id: document.getElementById("restore-snapshot-id").value.trim(),
        target: document.getElementById("restore-target").value.trim(),
        include_path: document.getElementById("restore-include").value.trim() || undefined,
      }),
    });
    flash(payload.ok ? "Restore completed." : "Restore failed.", payload.ok ? "info" : "error");
    await loadAll();
  });

  document.getElementById("export-config").addEventListener("click", async () => {
    const payload = await api("/api/config/export");
    document.getElementById("import-bundle").value = JSON.stringify(payload.bundle, null, 2);
    flash("Current configuration exported to the text box, including password and rclone config.");
  });

  document.getElementById("import-config").addEventListener("click", async () => {
    try {
      const importedJson = JSON.parse(document.getElementById("import-bundle").value);
      const payload = await api("/api/config/import", {
        method: "POST",
        body: JSON.stringify(importedJson),
      });
      state.config = payload.config;
      renderConfig();
      flash("Configuration imported.");
    } catch (error) {
      flash(`Import failed: ${error.message}`, "error");
    }
  });

  try {
    renderLogs();
    renderSyncState();
    await loadAll();
    schedulePolling();
  } catch (error) {
    flash(error.message, "error");
  }
});
