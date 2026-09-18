"use strict";
const $ = (id) => document.getElementById(id);
const activeStates = new Set(["starting", "running", "stopping"]);
let token = null, connected = false, busy = false, dirty = false, cursor = 0;
let savedConfig = null, state = { status: "idle", stats: {} }, activeSignature = "", instance = null;
let visibleLogs = [], toastTimer;

function toast(message, error = false) {
  const element = $("toast");
  element.querySelector("span").textContent = message;
  element.classList.toggle("error", error);
  element.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { element.hidden = true; }, 3500);
}

function setConnected(value) {
  connected = value;
  $("connection").className = `connection ${value ? "online" : "offline"}`;
  $("connection").querySelector("span:last-child").textContent = value ? "本地服务已连接" : "本地服务未连接";
  $("connection-error").hidden = value;
  updateControls();
}

async function api(path, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const options = { signal: controller.signal, cache: "no-store" };
    if (body !== undefined) {
      options.method = "POST";
      options.headers = { "Content-Type": "application/json", "X-Delta1-Token": token };
      options.body = JSON.stringify(body);
    }
    const response = await fetch(path, options);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `请求失败 (${response.status})`);
    return result;
  } finally { clearTimeout(timer); }
}

function fillConfig(config) {
  savedConfig = config;
  $("symbols").value = config.symbols.join("\n");
  $("interval").value = config.interval;
  $("output-dir").value = config.output_dir;
  dirty = false;
  countSymbols();
  updateControls();
}

function countSymbols() {
  const text = $("symbols").value.trim();
  const values = text.replace(/#[^\n]*/g, "").split(/[\s,;，；\[\]'\"]+/).filter(Boolean);
  $("symbol-count").textContent = new Set(values.map(value => value.toUpperCase())).size;
}

function updateControls() {
  const active = activeStates.has(state.status);
  const locked = active || busy || !connected;
  for (const name of ["symbols", "interval", "output-dir", "import", "save"]) $(name).disabled = locked;
  $("start").disabled = locked;
  $("stop").disabled = !connected || busy || !["starting", "running"].includes(state.status);
  $("start").querySelector("span").textContent = state.status === "starting" ? "正在启动…" : active ? "采集中" : "开始采集";
  $("stop").querySelector("span").textContent = state.status === "stopping" ? "正在停止…" : "停止采集";
  const hint = active ? "运行中参数已锁定，停止后可修改" : dirty ? "有未保存的修改，开始采集时也会自动保存" : "设置将保留到下次打开";
  $("config-hint").replaceChildren();
  const dot = document.createElement("span"); dot.className = "small-dot";
  $("config-hint").append(dot, document.createTextNode(hint));
}

function getForm() {
  const symbols = $("symbols").value;
  const interval = Number($("interval").value);
  const output_dir = $("output-dir").value.trim();
  if (!symbols.trim()) { $("symbols").focus(); throw new Error("请先填写至少一个标的。"); }
  if (!Number.isFinite(interval) || interval <= 0) { $("interval").focus(); throw new Error("采集间隔必须是大于 0 的秒数。"); }
  if (!output_dir) { $("output-dir").focus(); throw new Error("请填写数据保存目录。"); }
  return { symbols, interval, output_dir };
}

function appendLogs(entries) {
  const fragment = document.createDocumentFragment();
  for (const entry of entries) {
    visibleLogs.push(entry);
    const line = document.createElement("div");
    line.className = `log-line ${entry.level.toLowerCase()}`;
    const stamp = document.createElement("span"); stamp.className = "log-time";
    stamp.textContent = timeText(entry.at);
    const level = document.createElement("span"); level.className = "log-level";
    level.textContent = entry.level === "WARNING" ? "WARN" : entry.level;
    const message = document.createElement("span"); message.className = "log-message"; message.textContent = entry.message;
    line.append(stamp, level, message); fragment.append(line);
  }
  $("logs").append(fragment);
  while (visibleLogs.length > 600) { visibleLogs.shift(); $("logs").firstChild.remove(); }
  if (entries.length && $("autoscroll").checked) $("console").scrollTop = $("console").scrollHeight;
}

function timeText(value) {
  if (!value) return "—";
  return new Date(value).toLocaleTimeString("zh-CN", { hour12: false });
}

function render(next) {
  // A slow polling response must not overwrite a newer start/stop response.
  if (next.instance_id === instance && next.log_cursor < cursor) return;
  state = next;
  const names = { idle: "未启动", starting: "准备中", running: "采集中", stopping: "停止中", stopped: "已停止", failed: "运行异常" };
  const descriptions = { idle: "准备好配置，即可开始", starting: "正在建立本次采集任务", running: "后台采集中，关闭页面不会停止", stopping: "等待当前请求完成并落盘", stopped: "数据已保存，可再次开始", failed: "请查看下方错误与运行日志" };
  $("status-text").textContent = names[next.status] || next.status;
  $("status-description").textContent = descriptions[next.status] || "";
  $("status-dot").className = `status-dot ${next.status}`;
  $("monitor-status").className = `pill ${next.status}`;
  $("monitor-status").querySelector("span:last-child").textContent = next.status === "idle" ? "等待开始" : names[next.status];
  $("poll-count").textContent = next.stats.polls || 0;
  $("batch-count").textContent = next.stats.batches || 0;
  $("batch-note").textContent = `成功 ${next.stats.successful || 0} · 异常 ${next.stats.unsuccessful || 0}`;
  $("latency").textContent = next.stats.last_latency_ms ?? "—";
  $("last-response").textContent = next.stats.last_response_at ? `最近接收 ${timeText(next.stats.last_response_at)}` : "尚未收到响应";
  $("run-id").textContent = next.run_id || "尚未开始";
  $("run-id").title = next.run_id || "尚未开始";
  $("started-at").textContent = timeText(next.stats.started_at);
  $("console-live").textContent = next.status === "running" ? "● LIVE" : next.status === "stopping" ? "STOPPING" : "STANDBY";
  $("console-live").classList.toggle("live", next.status === "running");
  $("console-empty").hidden = activeStates.has(next.status) || Boolean(next.stats.batches) || next.status === "failed";
  $("run-error").hidden = !next.error;
  $("run-error").textContent = next.error ? `采集已停止：${next.error}` : "";
  if (activeStates.has(next.status) && next.active_config) {
    const signature = JSON.stringify(next.active_config);
    if (signature !== activeSignature) { fillConfig(next.active_config); activeSignature = signature; }
  } else activeSignature = "";
  const output = next.active_config?.output_dir || savedConfig?.output_dir || "";
  $("actual-output").textContent = output; $("actual-output").title = output;
  appendLogs((next.logs || []).filter(item => item.id > cursor));
  cursor = next.log_cursor;
  updateControls();
}

async function action(route, bodyFactory) {
  $("form-error").hidden = true;
  busy = true; updateControls();
  try {
    const result = await api(route, bodyFactory());
    if (result.config) fillConfig(result.config);
    if (result.state) render(result.state);
    toast(route === "/api/config" ? "配置已保存" : route === "/api/start" ? "采集任务已启动" : "停止请求已发送");
  } catch (error) {
    $("form-error").textContent = error.name === "AbortError" ? "请求未能及时返回，请查看运行状态后重试。" : error.message;
    $("form-error").hidden = false;
  } finally { busy = false; updateControls(); }
}

async function poll() {
  try {
    if (busy) return;
    if (!token) {
      const initial = await api("/api/bootstrap");
      if (instance !== initial.state.instance_id) {
        cursor = 0; visibleLogs = []; $("logs").replaceChildren();
      }
      token = initial.token; instance = initial.state.instance_id;
      if (!dirty) fillConfig(initial.config);
      render(initial.state);
    } else {
      const next = await api(`/api/state?after=${cursor}`);
      if (next.instance_id !== instance) {
        // A restarted server has a new token and an independent log sequence.
        token = null; cursor = 0; visibleLogs = []; $("logs").replaceChildren();
      } else render(next);
    }
    setConnected(true);
  } catch (_) { setConnected(false); token = null; }
  finally { setTimeout(poll, connected ? 1000 : 2000); }
}

function route() {
  const trading = location.hash === "#trading";
  $("realtime-page").hidden = trading; $("trading-page").hidden = !trading;
  $("breadcrumb-page").textContent = trading ? "交易数据下载" : "实时下载";
  document.title = `Delta1 · ${trading ? "交易数据下载" : "实时数据下载"}`;
  for (const [name, selected] of [["nav-trading", trading], ["nav-realtime", !trading]]) {
    $(name).classList.toggle("active", selected);
    if (selected) $(name).setAttribute("aria-current", "page"); else $(name).removeAttribute("aria-current");
  }
}

async function copy(value) {
  try { await navigator.clipboard.writeText(value); toast("已复制到剪贴板"); }
  catch (_) { toast("复制失败，请手动选择文本复制。", true); }
}

$("config-form").addEventListener("submit", event => { event.preventDefault(); action("/api/start", getForm); });
$("save").addEventListener("click", () => action("/api/config", getForm));
$("stop").addEventListener("click", () => action("/api/stop", () => ({})));
for (const name of ["symbols", "interval", "output-dir"]) $(name).addEventListener("input", () => { dirty = true; countSymbols(); updateControls(); $("form-error").hidden = true; });
$("import").addEventListener("click", () => $("file-input").click());
$("file-input").addEventListener("change", async () => {
  const files = [...$("file-input").files];
  if (!files.length) return;
  busy = true; updateControls();
  try {
    if (files.reduce((size, file) => size + file.size, 0) > 900000) throw new Error("标的文件合计不能超过 900 KB。");
    const result = await api("/api/symbols/parse", { files: await Promise.all(files.map(async file => ({ name: file.name, text: await file.text() }))) });
    $("symbols").value = result.symbols.join("\n"); dirty = true; countSymbols();
    toast(`已导入 ${result.symbols.length} 个标的，保存或开始采集后生效`);
  } catch (error) { toast(error.message, true); }
  finally { $("file-input").value = ""; busy = false; updateControls(); }
});
$("clear-logs").addEventListener("click", () => { visibleLogs = []; $("logs").replaceChildren(); });
$("copy-logs").addEventListener("click", () => copy(visibleLogs.map(row => `${row.at} ${row.level} ${row.message}`).join("\n")));
$("copy-path").addEventListener("click", () => copy($("actual-output").textContent));
$("autoscroll").addEventListener("change", () => { if ($("autoscroll").checked) $("console").scrollTop = $("console").scrollHeight; });
window.addEventListener("hashchange", route);
window.addEventListener("resize", () => { if ($("autoscroll").checked) $("console").scrollTop = $("console").scrollHeight; });
function updateClock() { $("clock").textContent = new Date().toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }); }
route(); updateClock(); setInterval(updateClock, 30000); poll();
