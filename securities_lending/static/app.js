"use strict";
const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt = (value, digits = 2) => value == null ? "—" : Number(value).toLocaleString("zh-CN", {maximumFractionDigits:digits});
let currentStatus = null;
let lastQuery = null;
let busy = false;

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "请求失败");
  return value;
}
function setBusy(value) {
  busy = value;
  ["refresh", "query-button", "save-settings"].forEach((id) => $(id).disabled = value);
  $("query-button").textContent = value ? "处理中…" : "查询券源 →";
}
function alerts(notices = []) {
  $("alerts").innerHTML = [...new Set([...(currentStatus?.warnings || []), ...notices])].map((s) => `<div class="alert">${esc(s)}</div>`).join("");
}
function showStatus(status) {
  currentStatus = status;
  $("run-date").textContent = `${status.date.replaceAll("-", " / ")} · 运行日`;
  $("demo-banner").hidden = status.mode !== "demo";
  const labels = {ready:"当日券单已就绪", cached:"使用当日本地缓存", unavailable:"当日券单未就绪", loading:"正在同步券单"};
  $("source-state").textContent = labels[status.state] || status.state;
  $("source-dot").className = "status-dot" + (status.state === "cached" ? " warning" : status.state === "unavailable" ? " error" : "");
  $("source-description").textContent = `${status.files.length} 份文件 · ${fmt(status.security_count, 0)} 只标的 · ${fmt(status.record_count, 0)} 笔券源`;
  $("last-sync").textContent = status.downloaded_at ? `券单下载于 ${status.downloaded_at.slice(11,19)}` : "尚未同步";
  $("provenance-body").innerHTML = `<div>运行日期：${esc(status.date)}（北京时间）</div><div>来源目录：${esc(status.source_dir || "正在读取")}</div><div>读取方式：${status.selection === "merge" ? "合并独立券源" : "最新文件"}</div>` + status.files.map((file) => `<div class="file-entry"><strong>${esc(file.name)}</strong> · ${fmt(file.records,0)} 行 · ${fmt(file.size / 1024)} KB<div>本地缓存：${esc(file.path)}</div><div>表头第 ${file.header_row} 行 · ${esc(Object.entries(file.columns).map(([k,v])=>`${k}: ${v}`).join(" / "))}</div><code>SHA256 ${esc(file.sha256)}</code></div>`).join("");
  alerts();
}
function rateText(item) {
  const numeric = item.rate_min == null ? "" : item.rate_min === item.rate_max ? `${fmt(item.rate_min,4)}%` : `${fmt(item.rate_min,4)}–${fmt(item.rate_max,4)}%`;
  return [numeric, ...item.rate_raw].filter(Boolean).join(" / ") || "—";
}
function rowRate(row) { return row.rate == null ? row.rate_raw || "—" : `${fmt(row.rate,4)}%`; }
function renderResults(data) {
  lastQuery = data;
  showStatus(data.status);
  alerts(data.warnings);
  const s = data.summary;
  $("metric-matched").textContent = s.matched;
  $("metric-quantity").textContent = fmt(s.quantity == null ? null : s.quantity / 10000);
  $("metric-nominal").textContent = fmt(s.nominal == null ? null : s.nominal / 10000);
  $("metric-unmatched").textContent = s.unmatched;
  $("metric-inputs").textContent = `已查询 ${s.inputs} 项输入 · 按证券代码去重`;
  $("metric-quantity-note").textContent = s.quantity_complete ? "按标的去重汇总" : "仅合计已知数量 · 存在缺失或未匹配";
  $("metric-nominal-note").textContent = `${s.nominal_complete ? "名义本金" : "仅合计已知名本"}${s.nominal_estimated ? " · 含价格估算" : " · 取自券单"}`;
  $("result-count").textContent = `${s.matched} 只标的`;
  $("export").disabled = !s.matched;
  if (data.status.state === "unavailable") {
    $("result-body").innerHTML = '<div class="empty-state"><div class="empty-icon">!</div><h3>当日券单尚不可用</h3><p>请检查数据设置和共享盘连接，再同步当日券单。</p><span>数据未就绪时，未匹配结果不代表没有可融库存。</span></div>';
    return;
  }
  let rows = "";
  const rendered = new Set();
  for (const group of data.results) {
    if (!group.matches.length) {
      rows += `<tr class="not-found"><td>${esc(group.input)}</td><td colspan="5">当日券单未匹配 · 请核对代码或名称</td></tr>`;
    }
    for (const item of group.matches) {
      if (rendered.has(item.code)) continue;
      rendered.add(item.code);
      rows += `<tr><td><strong class="security-name">${esc(item.name)}</strong><span class="code">${esc(item.code)}</span></td><td><span class="industry-tag">${esc(item.industry || "待补充")}</span><small class="subtext">${esc(item.industry_source || "券单未提供行业")}</small></td><td class="numeric">${fmt(item.quantity == null ? null : item.quantity / 10000)}<small class="subtext">${fmt(item.quantity,0)} 股${item.quantity_complete ? "" : " · 部分缺失"}</small></td><td class="numeric">${fmt(item.nominal == null ? null : item.nominal / 10000)}<small class="subtext">${item.nominal_estimated ? "含价格估算" : "券单名本"}${item.nominal_complete ? "" : " · 部分缺失"}</small></td><td class="numeric">${esc(rateText(item))}<small class="subtext">${item.rate_complete ? "券单费率口径" : "部分费率缺失"}</small></td><td class="numeric">${item.rows.length}<small class="subtext">${item.quantity === 0 && item.quantity_complete ? "当前数量为零" : "笔券源"}</small></td></tr>`;
      rows += `<tr class="detail-row"><td colspan="6"><details class="row-details"><summary>查看 ${item.rows.length} 笔原始券源与文件来源</summary><div class="table-scroll"><table><thead><tr><th>文件 / Excel 行号</th><th class="numeric">可融数量（股）</th><th class="numeric">名本（元）</th><th>出借费率</th><th>期限</th><th>名本来源</th></tr></thead><tbody>${item.rows.map((r)=>`<tr><td>${esc(r.file)} : ${r.row}</td><td class="numeric">${fmt(r.quantity,0)}</td><td class="numeric">${fmt(r.nominal)}</td><td>${esc(rowRate(r))}</td><td>${esc(r.term || "—")}</td><td>${esc(r.nominal_source)}</td></tr>`).join("")}</tbody></table></div></details></td></tr>`;
    }
  }
  $("result-body").innerHTML = `<div class="table-scroll"><table><thead><tr><th>证券 / 代码</th><th>所属行业</th><th class="numeric">可融数量（万股）</th><th class="numeric">名本（万元）</th><th class="numeric">出借费率</th><th class="numeric">券源</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
function clearQuery() {
  lastQuery = null;
  ["matched","quantity","nominal","unmatched"].forEach(k=>$("metric-"+k).textContent="—");
  $("metric-inputs").textContent="等待查询";
  $("metric-quantity-note").textContent="按标的去重汇总";
  $("metric-nominal-note").textContent="名义本金 · 保留数据口径";
  $("export").disabled=true;
  $("result-count").textContent="等待查询";
  $("result-body").innerHTML='<div class="empty-state"><div class="empty-icon">⌕</div><h3>券单已更新</h3><p>输入标的，查询本次同步的库存。</p></div>';
}
async function query() {
  if (busy) return;
  const symbols = $("symbols").value.trim();
  if (!symbols) { $("symbols").focus(); alerts(["请输入至少一个证券代码或名称"]); return; }
  setBusy(true);
  clearQuery();
  $("result-body").innerHTML='<div class="results-loading">正在匹配券源与补充行业…</div>';
  try { renderResults(await api("/api/query", {symbols})); }
  catch (error) { alerts([error.message]); $("result-body").innerHTML='<div class="empty-state"><h3>查询未完成</h3><p>请检查上方提示后重试。</p></div>'; }
  finally { setBusy(false); }
}
$("query-form").addEventListener("submit", (event)=>{event.preventDefault();query();});
$("symbols").addEventListener("keydown", (event)=>{if(event.key==="Enter"&&(event.ctrlKey||event.metaKey)){event.preventDefault();query();}});
document.querySelectorAll("[data-example]").forEach((button)=>button.addEventListener("click",()=>{$("symbols").value=button.dataset.example;query();}));
$("refresh").addEventListener("click",async()=>{
  if(busy) return;
  setBusy(true); clearQuery();
  try { showStatus(await api("/api/refresh",{})); }
  catch(error) { alerts([error.message]); }
  finally { setBusy(false); }
});
async function openSettings() {
  if(busy) return;
  try {
    const config = await api("/api/config");
    const form = $("settings-form");
    for(const [name,value] of Object.entries(config)) {
      const field = form.elements.namedItem(name);
      if(!field) continue;
      if(field.type==="checkbox") field.checked=value;
      else field.value=name==="columns" ? JSON.stringify(value,null,2) : value ?? "";
    }
    $("settings-error").textContent=currentStatus?.mode==="demo"?"当前为演示模式；保存的公司配置在正常启动时生效。":"";
    $("settings-dialog").showModal();
  } catch(error) { alerts([error.message]); }
}
["settings-nav","settings-source"].forEach(id=>$(id).addEventListener("click",openSettings));
["close-settings","cancel-settings"].forEach(id=>$(id).addEventListener("click",()=>$("settings-dialog").close()));
$("settings-form").addEventListener("submit",async(event)=>{
  event.preventDefault(); if(busy) return;
  try {
    const form=event.target;
    const config=Object.fromEntries(new FormData(form).entries());
    config.wind_enabled=form.elements.wind_enabled.checked;
    config.header_row=config.header_row?Number(config.header_row):null;
    config.columns=JSON.parse(config.columns||"{}");
    setBusy(true);
    showStatus(await api("/api/config",config));
    clearQuery(); $("settings-dialog").close();
  } catch(error) { $("settings-error").textContent=error.message; }
  finally { setBusy(false); }
});
$("export").addEventListener("click",()=>{
  if(!lastQuery) return;
  const rows=[["数据日期","数据状态","模式","证券代码","证券名称","行业","行业来源","可融数量（股）","名本（元）","名本来源","出借费率","期限","文件","Excel行号"]];
  const seen=new Set();
  for(const group of lastQuery.results) for(const item of group.matches) {
    if(seen.has(item.code)) continue; seen.add(item.code);
    for(const row of item.rows) rows.push([lastQuery.status.date,lastQuery.status.state,lastQuery.status.mode,item.code,item.name,row.industry,row.industry_source,row.quantity,row.nominal,row.nominal_source,rowRate(row),row.term,row.file,row.row]);
  }
  const cell=(v)=>{let t=String(v??"");if(/^[=+\-@\t\r]/.test(t))t="'"+t;return '"'+t.replaceAll('"','""')+'"';};
  const blob=new Blob(["\ufeff"+rows.map(r=>r.map(cell).join(",")).join("\r\n")],{type:"text/csv;charset=utf-8"});
  const url=URL.createObjectURL(blob);const link=document.createElement("a");link.href=url;link.download=`券源查询_${lastQuery.status.mode}_${lastQuery.status.date}.csv`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
async function bootstrap() {
  setBusy(true);
  try { showStatus(await api("/api/status")); }
  catch(error) { alerts([error.message]); }
  finally { setBusy(false); }
}
bootstrap();
// Avoid keeping yesterday's answers visible across midnight.
setInterval(async()=>{
  if(busy || document.hidden) return;
  const day=new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
  if(currentStatus && currentStatus.date!==day) {clearQuery();await bootstrap();}
},30000);
