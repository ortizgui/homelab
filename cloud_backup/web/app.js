const POLL_INTERVAL_IDLE_MS = 15000;
const POLL_INTERVAL_ACTIVE_MS = 3000;
const FULL_REFRESH_INTERVAL_IDLE_MS = 45000;
const FULL_REFRESH_INTERVAL_ACTIVE_MS = 9000;
const BACKUP_REQUEST_TIMEOUT_MS = 5000;

const state = {
  config: null,
  remoteQuota: null,
  summary: null,
  status: null,
  runtime: null,
  logs: [],
  lastUpdated: {
    remoteQuota: null,
    summary: null,
    status: null,
    logs: null,
    runtime: null,
  },
  sync: {
    remoteQuota: "idle",
    summary: "idle",
    runtime: "idle",
    status: "idle",
    logs: "idle",
  },
  requestIds: {
    remoteQuota: 0,
    summary: 0,
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

function formatPercent(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return null;
  }
  return `${Math.max(0, Math.min(100, value * 100)).toFixed(1)}%`;
}

function formatBytes(value) {
  if (typeof value !== "number" || Number.isNaN(value) || value < 0) {
    return null;
  }
  if (value === 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  const exponent = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  const scaled = value / (1024 ** exponent);
  return `${scaled.toFixed(scaled >= 100 || exponent === 0 ? 0 : scaled >= 10 ? 1 : 2)} ${units[exponent]}`;
}

function formatDuration(seconds) {
  if (typeof seconds !== "number" || Number.isNaN(seconds) || seconds < 0) {
    return null;
  }
  if (seconds < 60) {
    return `${Math.round(seconds)}s`;
  }
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.round(seconds % 60);
  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  if (minutes > 0) {
    return `${minutes}m ${secs}s`;
  }
  return `${secs}s`;
}

function hasActiveRun() {
  return Boolean(state.runtime?.current_run || state.summary?.current_run || state.status?.current_run);
}

function setSyncState(key, nextState) {
  state.sync[key] = nextState;
  renderSyncState();
  renderCardLoadingState();
}

function renderSyncState() {
  const node = document.getElementById("sync-status");
  const detail = document.getElementById("sync-updated");
  const hardError = state.sync.summary === "error" || state.sync.runtime === "error";
  const softError = !hardError && (state.sync.status === "error" || state.sync.remoteQuota === "error" || state.sync.logs === "error");
  const currentStates = Object.values(state.sync);

  if (hardError) {
    node.textContent = "Sync degraded";
    node.className = "sync-pill sync-error";
  } else if (softError) {
    node.textContent = "Partial sync";
    node.className = "sync-pill sync-warn";
  } else if (hasActiveRun() || currentStates.includes("loading")) {
    node.textContent = hasActiveRun() ? "Live monitoring" : "Syncing";
    node.className = "sync-pill sync-active";
  } else {
    node.textContent = "In sync";
    node.className = "sync-pill";
  }

  const latestTimestamp = [state.lastUpdated.runtime, state.lastUpdated.remoteQuota, state.lastUpdated.summary, state.lastUpdated.status, state.lastUpdated.logs]
    .filter(Boolean)
    .sort()
    .at(-1);
  detail.textContent = latestTimestamp
    ? `Last update: ${formatTimestamp(latestTimestamp)}`
    : "The dashboard is connecting to the backend.";
}

function setCardLoading(cardId, isLoading) {
  const node = document.getElementById(cardId);
  if (!node) {
    return;
  }
  node.classList.toggle("loading-card", isLoading);
}

function renderCardLoadingState() {
  const summaryPending = state.sync.summary === "loading" && !state.summary;
  const quotaPending = state.sync.remoteQuota === "loading" && !state.remoteQuota;
  const statusPending = state.sync.status === "loading" && !state.status;
  const logsPending = state.sync.logs === "loading" && state.logs.length === 0;
  const runtimePending = state.sync.runtime === "loading" && !state.runtime;
  const progressPending = runtimePending && !hasActiveRun();

  setCardLoading("card-safety-gate", summaryPending && statusPending);
  setCardLoading("card-snapshots", summaryPending && statusPending);
  setCardLoading("card-repository-usage", quotaPending);
  setCardLoading("card-backup-progress", progressPending);
  setCardLoading("card-last-backup-result", summaryPending && logsPending);
  setCardLoading("card-blocked-reasons", summaryPending && statusPending);
}

function renderRunIndicator() {
  const node = document.getElementById("run-indicator");
  const currentRun = state.runtime?.current_run || state.summary?.current_run || state.status?.current_run;
  if (!currentRun) {
    node.textContent = "";
    node.className = "run-indicator hidden";
    return;
  }
  const actionLabel = currentRun.action[0].toUpperCase() + currentRun.action.slice(1);
  const startedAt = formatTimestamp(currentRun.started_at);
  const tag = currentRun.tag ? ` Tag: ${currentRun.tag}.` : "";
  const percent = currentRun.action === "backup" ? formatPercent(currentRun.progress?.percent_done) : null;
  const percentLabel = percent ? ` Progress: ${percent}.` : "";
  node.textContent = `${actionLabel} running now.${tag}${percentLabel} Started at ${startedAt}.`;
  node.className = "run-indicator";
}

function renderBackupProgress(currentRun) {
  const percentNode = document.getElementById("backup-progress-percent");
  const barNode = document.getElementById("backup-progress-bar");
  const summaryNode = document.getElementById("backup-progress-summary");
  const currentNode = document.getElementById("backup-progress-current");

  if (!currentRun || currentRun.action !== "backup") {
    percentNode.textContent = "Idle";
    barNode.style.width = "0%";
    summaryNode.textContent = "No backup in progress.";
    currentNode.textContent = "";
    return;
  }

  const progress = currentRun.progress || {};
  const percent = formatPercent(progress.percent_done);
  percentNode.textContent = percent || "Running";
  barNode.style.width = percent || "8%";

  const summaryParts = [];
  if (typeof progress.files_done === "number" && typeof progress.total_files === "number") {
    summaryParts.push(`${progress.files_done} / ${progress.total_files} files`);
  }
  const bytesDone = formatBytes(progress.bytes_done);
  const totalBytes = formatBytes(progress.total_bytes);
  if (bytesDone && totalBytes) {
    summaryParts.push(`${bytesDone} / ${totalBytes}`);
  } else if (bytesDone) {
    summaryParts.push(bytesDone);
  }
  const remaining = formatDuration(progress.seconds_remaining);
  if (remaining) {
    summaryParts.push(`ETA ${remaining}`);
  }
  summaryNode.textContent = summaryParts.join(" | ") || "Collecting progress from restic.";
  currentNode.textContent = progress.current_file ? `Current file: ${progress.current_file}` : "";
}

function findLatestBackupLog() {
  if (state.summary?.latest_backup) {
    return state.summary.latest_backup;
  }
  return state.logs
    .slice()
    .reverse()
    .find((entry) => entry.action === "backup" && Object.prototype.hasOwnProperty.call(entry, "ok"));
}

function renderLatestBackupResult() {
  const resultNode = document.getElementById("last-backup-result");
  const summaryNode = document.getElementById("last-backup-result-summary");
  const detailNode = document.getElementById("last-backup-result-detail");
  const currentRun = state.runtime?.current_run || state.summary?.current_run || state.status?.current_run;

  if (currentRun?.action === "backup") {
    const progress = currentRun.progress || {};
    const percent = formatPercent(progress.percent_done);
    resultNode.textContent = percent || "Running";
    resultNode.className = "metric metric-small metric-accent";
    summaryNode.textContent = `Backup in progress since ${formatTimestamp(currentRun.started_at)}.`;
    detailNode.textContent = progress.current_file ? `Current file: ${progress.current_file}` : "Collecting progress from restic.";
    return;
  }

  const latest = findLatestBackupLog();
  if (!latest) {
    resultNode.textContent = "Unknown";
    resultNode.className = "metric metric-small";
    summaryNode.textContent = "No backup recorded yet.";
    detailNode.textContent = "";
    return;
  }

  const ok = latest.ok === true;
  resultNode.textContent = ok ? "Success" : "Failed";
  resultNode.className = `metric metric-small ${ok ? "metric-success" : "metric-danger"}`;
  const tag = latest.tag ? ` Tag: ${latest.tag}.` : "";
  summaryNode.textContent = `${ok ? "Last backup finished successfully." : "Last backup finished with errors."}${tag} ${formatTimestamp(latest.timestamp)}`.trim();
  const detail = (latest.detail || "").trim();
  if (detail) {
    detailNode.textContent = detail;
  } else {
    detailNode.textContent = state.runtime?.last_successful_backup || state.summary?.last_successful_backup || state.status?.last_successful_backup
      ? `Last successful backup: ${formatTimestamp(state.runtime?.last_successful_backup || state.summary?.last_successful_backup || state.status?.last_successful_backup)}`
      : "";
  }
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
  const payload = state.status || {};
  const summary = state.summary || {};
  const preflight = payload.preflight || summary.latest_preflight || null;
  const currentRun = state.runtime?.current_run || summary.current_run || payload.current_run;
  renderRunIndicator();
  renderBackupProgress(currentRun);
  renderLatestBackupResult();
  document.getElementById("status-gate").textContent = preflight ? (preflight.ok ? "PASS" : "BLOCKED") : "UNAVAILABLE";
  document.getElementById("status-failures").textContent = preflight
    ? ((preflight.failures || []).join("\n") || "No blocking failures.")
    : "Waiting for the latest preflight result.";
  document.getElementById("snapshot-count").textContent = Array.isArray(payload.snapshots)
    ? String(payload.snapshots.length)
    : (summary.latest_backup?.snapshot_id ? "1+" : "-");
  document.getElementById("last-backup").textContent = state.runtime?.last_successful_backup || summary.last_successful_backup || payload.last_successful_backup || "No successful backup yet.";
  const quota = state.remoteQuota?.quota || {};
  const used = formatBytes(quota.used);
  const total = formatBytes(quota.total);
  const free = formatBytes(quota.free);
  document.getElementById("repo-usage").textContent = used && total ? `${used} / ${total}` : "N/A";
  document.getElementById("repo-files").textContent = free
    ? `Free: ${free}`
    : (state.remoteQuota?.ok === false ? (state.remoteQuota.message || "Remote quota unavailable.") : "Waiting for remote quota.");
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
  (preflight?.source_results || []).forEach((entry) => {
    const li = document.createElement("li");
    li.textContent = `${entry.path}: exists=${entry.exists} readable=${entry.readable} non_empty=${entry.non_empty}`;
    preflightList.appendChild(li);
  });
  if (!preflightList.children.length) {
    const li = document.createElement("li");
    li.textContent = preflight ? "No blocked sources." : "Detailed source checks will appear after a successful status refresh.";
    preflightList.appendChild(li);
  }
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

async function loadSummary() {
  const requestId = ++state.requestIds.summary;
  setSyncState("summary", "loading");
  try {
    const payload = await api("/api/summary", { timeoutMs: 15000 });
    if (requestId !== state.requestIds.summary) {
      return;
    }
    state.summary = payload;
    state.lastUpdated.summary = payload.timestamp;
    setSyncState("summary", "idle");
    renderStatus();
  } catch (error) {
    if (requestId === state.requestIds.summary) {
      setSyncState("summary", "error");
    }
    throw error;
  }
}

async function loadRemoteQuota() {
  const requestId = ++state.requestIds.remoteQuota;
  setSyncState("remoteQuota", "loading");
  try {
    const payload = await api("/api/remote-quota", { timeoutMs: 15000 });
    if (requestId !== state.requestIds.remoteQuota) {
      return;
    }
    state.remoteQuota = payload;
    state.lastUpdated.remoteQuota = payload.timestamp;
    setSyncState("remoteQuota", "idle");
    renderStatus();
  } catch (error) {
    if (requestId === state.requestIds.remoteQuota) {
      state.remoteQuota = {
        ok: false,
        message: error.message,
        quota: {},
      };
      setSyncState("remoteQuota", "error");
      renderStatus();
    }
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
    renderLatestBackupResult();
  } catch (error) {
    if (requestId === state.requestIds.logs) {
      setSyncState("logs", "error");
    }
    throw error;
  }
}

async function loadAll({ includeConfig = true } = {}) {
  const tasks = [
    loadSummary(),
    loadRuntime(),
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
  await Promise.allSettled([loadRemoteQuota(), loadSummary(), loadRuntime()]);
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
        await Promise.allSettled([loadRemoteQuota(), loadSummary(), loadLogs()]);
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
      progress: {
        phase: "starting",
        percent_done: 0,
        files_done: 0,
        bytes_done: 0,
        current_file: null,
        current_files: [],
      },
    },
    last_successful_backup: state.runtime?.last_successful_backup || state.summary?.last_successful_backup || state.status?.last_successful_backup || null,
  };
  renderStatus();
}

document.addEventListener("DOMContentLoaded", async () => {
  renderCardLoadingState();
  document.querySelectorAll(".sidebar button[data-view]").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.view));
  });

  document.getElementById("reload-status").addEventListener("click", async () => {
    await Promise.allSettled([loadAll({ includeConfig: false }), loadStatus()]);
    flash("Status reloaded.");
  });

  document.getElementById("run-preflight").addEventListener("click", async () => {
    const payload = await api("/api/preflight");
    flash(payload.ok ? "Preflight passed." : `Preflight blocked: ${payload.failures.join(", ")}`, payload.ok ? "info" : "error");
    await refreshStatus();
  });

  document.getElementById("run-backup").addEventListener("click", async () => {
    if (hasActiveRun() && (state.runtime?.current_run || state.summary?.current_run || state.status?.current_run)?.action === "backup") {
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
        await Promise.allSettled([loadRemoteQuota(), loadSummary(), loadLogs(), loadStatus()]);
      } catch {
        // Ignore status refresh failures and fall back to the original error.
      }
      const currentRun = state.runtime?.current_run || state.summary?.current_run || state.status?.current_run;
      if (currentRun?.action === "backup") {
        flash("Backup is still running on the server. The web request timed out while waiting for completion.", "info");
      } else {
        flash(`Backup failed to start: ${error.message}`, "error");
      }
    } finally {
      const activeRun = state.runtime?.current_run || state.summary?.current_run || state.status?.current_run;
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

  // ===== Restore & Download =====

  let restoreSelectedPaths = new Set();
  let currentSnapshotId = null;

  async function loadSnapshotList() {
    const sel = document.getElementById("restore-snapshot-select");
    sel.innerHTML = '<option value="">— Loading snapshots —</option>';
    try {
      const payload = await api("/api/snapshots", { timeoutMs: 30000 });
      const snapshots = payload.snapshots || [];
      sel.innerHTML = '<option value="">— Select snapshot —</option>';
      snapshots.forEach((snap) => {
        const opt = document.createElement("option");
        opt.value = snap.short_id || snap.id;
        const time = formatTimestamp(snap.time) || snap.time || "?";
        const tag = snap.tags ? ` [${snap.tags.join(", ")}]` : "";
        const paths = snap.paths ? ` (${snap.paths.join(", ")})` : "";
        opt.textContent = `${time}${tag}  —  ${(snap.short_id || snap.id).slice(0, 12)}${paths}`;
        sel.appendChild(opt);
      });
    } catch (err) {
      sel.innerHTML = '<option value="">— Failed to load —</option>';
      flash(`Failed to load snapshots: ${err.message}`, "error");
    }
  }

  function renderRestoreBrowser(snapshotId, entries, basePath) {
    const container = document.getElementById("restore-browser");
    container.innerHTML = "";

    // Show current path
    const pathBar = document.createElement("div");
    pathBar.className = "browser-path-bar";
    pathBar.innerHTML = `<span class="browser-path-label">📁 ${basePath}</span>`;
    container.appendChild(pathBar);

    if (!entries || entries.length === 0) {
      container.innerHTML += '<p class="muted-copy">(empty directory)</p>';
      return;
    }

    const list = document.createElement("ul");
    list.className = "browser-list";

    // Parent directory entry (unless at root)
    if (basePath !== "/") {
      const li = document.createElement("li");
      li.className = "browser-item";
      const parentPath = basePath.split("/").slice(0, -1).join("/") || "/";
      li.innerHTML = `<span class="browser-toggle browser-up" data-path="${parentPath}">⬆</span>
        <span class="browser-name">..</span>`;
      li.querySelector(".browser-up").addEventListener("click", () => browseSnapshot(snapshotId, parentPath));
      list.appendChild(li);
    }

    entries.forEach((entry) => {
      const li = document.createElement("li");
      li.className = "browser-item";
      const icon = entry.type === "dir" ? "📁" : "📄";
      const checked = restoreSelectedPaths.has(entry.path) ? "checked" : "";
      li.innerHTML = `
        ${entry.type === "dir"
          ? `<span class="browser-toggle" data-path="${entry.path}">▶</span>`
          : '<span class="browser-toggle browser-toggle-empty"></span>'}
        <label class="browser-label">
          <input type="checkbox" class="browser-check" data-path="${entry.path}" ${checked}>
          <span class="browser-name">${icon} ${entry.name}</span>
        </label>`;
      if (entry.type === "dir") {
        li.querySelector(".browser-toggle").addEventListener("click", (e) => {
          browseSnapshot(snapshotId, entry.path);
        });
      }
      li.querySelector(".browser-check").addEventListener("change", (e) => {
        if (e.target.checked) {
          restoreSelectedPaths.add(entry.path);
        } else {
          restoreSelectedPaths.delete(entry.path);
        }
        updateRestoreSelectedBar();
      });
      list.appendChild(li);
    });

    container.appendChild(list);
  }

  async function browseSnapshot(snapshotId, path) {
    const container = document.getElementById("restore-browser");
    container.innerHTML = '<p class="muted-copy">Loading...</p>';
    try {
      const payload = await api(`/api/browse-snapshot/${snapshotId}?path=${encodeURIComponent(path)}`, { timeoutMs: 30000 });
      if (payload.ok) {
        renderRestoreBrowser(snapshotId, payload.entries, payload.path);
      } else {
        container.innerHTML = `<p class="muted-copy">Error: ${payload.message || "Failed to list directory"}</p>`;
      }
    } catch (err) {
      container.innerHTML = `<p class="muted-copy">Error: ${err.message}</p>`;
      flash(`Browse failed: ${err.message}`, "error");
    }
  }

  function updateRestoreSelectedBar() {
    const bar = document.getElementById("restore-selected-bar");
    const count = document.getElementById("restore-selected-count");
    const btn = document.getElementById("run-restore-pack");
    const total = restoreSelectedPaths.size;
    count.textContent = `${total} item${total !== 1 ? "s" : ""} selected`;
    if (total > 0 && currentSnapshotId) {
      bar.classList.remove("hidden");
      btn.disabled = false;
    } else {
      bar.classList.add("hidden");
      btn.disabled = true;
    }
  }

  async function runRestorePack() {
    const btn = document.getElementById("run-restore-pack");
    const status = document.getElementById("restore-pack-status");
    const paths = Array.from(restoreSelectedPaths);
    if (!currentSnapshotId || paths.length === 0) return;

    btn.disabled = true;
    btn.textContent = "Restoring...";
    status.textContent = "Restore in progress. Large restores may take minutes...";

    try {
      const payload = await api("/api/actions/restore-pack", {
        method: "POST",
        body: JSON.stringify({
          snapshot_id: currentSnapshotId,
          paths: paths,
          target_name: `restore_${currentSnapshotId.slice(0, 8)}`,
        }),
        timeoutMs: 60 * 60 * 1000, // 1 hour timeout
      });
      if (payload.ok) {
        status.innerHTML = `Restore complete. <a href="${payload.download_url}" class="download-link" download>⬇ Download ${payload.file_name}</a> (${formatBytes(payload.file_size)})`;
        flash("Restore completed. Click download link.", "info");
      } else {
        status.textContent = `Restore failed: ${payload.message || "Unknown error"}`;
        flash("Restore failed.", "error");
      }
    } catch (err) {
      status.textContent = `Error: ${err.message}`;
      flash(`Restore error: ${err.message}`, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "⬇ Restore & Download";
    }
  }

  // Wire up restore panel events
  document.getElementById("restore-snapshot-select").addEventListener("change", (e) => {
    const snapId = e.target.value;
    currentSnapshotId = snapId || null;
    restoreSelectedPaths.clear();
    updateRestoreSelectedBar();
    if (snapId) {
      browseSnapshot(snapId, "/");
    } else {
      document.getElementById("restore-browser").innerHTML = '<p class="muted-copy">Select a snapshot above to browse.</p>';
    }
  });

  document.getElementById("run-restore-pack").addEventListener("click", runRestorePack);

  // Hook into view switching — load snapshots when restore tab opens
  document.querySelectorAll(".sidebar button[data-view]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.view === "restore") {
        loadSnapshotList();
      }
    });
  });
});
