"use strict";

const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const number = (value, digits = 2) => typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("en-US", {minimumFractionDigits: digits, maximumFractionDigits: digits}) : "—";
const shortTime = value => value ? new Date(value).toLocaleTimeString("zh-CN", {hour12:false, timeZone:"Asia/Shanghai"}) : "—";
const fullTime = value => value ? new Date(value).toLocaleString("zh-CN", {hour12:false,timeZone:"Asia/Shanghai"}) : "—";
const qualities = {unverified:["时间未核验","amber"],closed:["休市缓存","neutral"],stale:["历史 / 过期","amber"],warmup:["等待样本","neutral"],mixed_days:["跨交易日","amber"],error:["计算未就绪","red"],waiting:["等待行情","neutral"],disabled:["已停用","neutral"]};
const badge = key => {const [label, cls] = qualities[key] || qualities.waiting; return `<span class="badge ${cls}">${label}</span>`;};
let token = "", config = {}, state = null, templates = [], page = "overview", filter = "全部", root = "IC", selected = "AU.SHF", historyRows = [];
let toastTimer, loading = false, connected = false;

async function api(path, value) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 25000);
  try {
    const response = await fetch(path, value === undefined ? {signal:controller.signal} : {method:"POST",signal:controller.signal,headers:{"Content-Type":"application/json","X-Delta1-Token":token},body:JSON.stringify(value)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `请求失败：${response.status}`);
    return result;
  } finally { clearTimeout(timer); }
}
function toast(text) { $("toast").textContent=text; $("toast").hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$("toast").hidden=true,4200); }
function errorAt(id, text) {$(id).textContent=text || "";$(id).hidden=!text;}
function bySymbol(symbol) {return state?.quotes.find(q=>q.symbol===symbol);}
function uniqueQuotes() {
  const result = new Map();
  for (const quote of state?.quotes || []) {
    const key=quote.source_symbol || quote.symbol, existing=result.get(key);
    if (!existing || quote.symbol===key || quote.symbol==="AU.SHF") result.set(key,quote);
  }
  return [...result.values()];
}

function lineSvg(points, {width=420,height=180,compact=false,labels=false}={}) {
  points=points.filter(p=>typeof p.value==="number" && Number.isFinite(p.value));
  if (!points.length) return '<div class="chart-empty">暂无有效样本<br>采集后展示真实数据</div>';
  const left=compact?2:52,right=compact?2:19,top=compact?3:16,bottom=compact?3:35;
  const values=points.map(p=>p.value);let low=Math.min(...values),high=Math.max(...values);
  const margin=(high-low)*.15 || Math.max(Math.abs(high)*.00015,.01);low-=margin;high+=margin;
  const pw=width-left-right,ph=height-top-bottom;
  const times=points.map((p,i)=>labels?i:Date.parse(p.time));
  const minimum=Math.min(...times),maximum=Math.max(...times);
  const x=i=>maximum===minimum?left+pw/2:left+(times[i]-minimum)/(maximum-minimum)*pw;
  const y=v=>top+(high-v)/(high-low)*ph;
  const path=points.map((p,i)=>`${i?"L":"M"}${x(i).toFixed(2)},${y(p.value).toFixed(2)}`).join(" ");
  let grid="";
  if (!compact) {
    for(let i=0;i<4;i++){const gy=top+i*ph/3;grid+=`<line x1="${left}" x2="${width-right}" y1="${gy}" y2="${gy}" stroke="#edf1f2" stroke-dasharray="3 4"/><text x="${left-8}" y="${gy+3}" text-anchor="end" font-size="9" fill="#97a7ab">${number(high-i*(high-low)/3,high<20?3:1)}</text>`;}
    points.forEach((p,i)=>{if(labels||i===0||i===points.length-1){grid+=`<text x="${x(i)}" y="${height-11}" text-anchor="middle" font-size="9" fill="#81969b">${esc(labels?p.label:shortTime(p.time))}</text>`;}});
  }
  const dots=(labels||points.length===1)?points.map((p,i)=>`<circle cx="${x(i)}" cy="${y(p.value)}" r="${compact?2:3.5}" fill="#fff" stroke="#198679" stroke-width="2"><title>${esc(p.label||shortTime(p.time))} · ${number(p.value,3)}</title></circle>`).join(""):"";
  const area=points.length>1?`<path d="${path} L${x(points.length-1)},${top+ph} L${x(0)},${top+ph} Z" fill="#e7f3ee" opacity=".7"/>`:"";
  return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${labels?"期限结构":"真实采样价格曲线"}">${grid}${area}<path d="${path}" fill="none" stroke="#23897b" stroke-width="${compact?1.6:2}" stroke-linejoin="round"/>${dots}</svg>`;
}

function curveRows(product) {return uniqueQuotes().filter(q=>new RegExp(`^${product}\\d{4}\\.CFE$`).test(q.source_symbol)).sort((a,b)=>a.source_symbol.localeCompare(b.source_symbol));}
function curve(product, id, height=180) {
  const rows=curveRows(product);
  $(id).innerHTML=lineSvg(rows.map(q=>({value:q.mid,label:q.source_symbol.match(/\d{4}/)[0]})),{height,labels:true});
  return rows;
}
function quoteCard(q,label,code) {
  const change=q?.observed_change;
  return `<article class="index-card"><div class="card-top"><span class="card-title">${esc(label)}</span><span class="ticker">${esc(code)}</span></div><div class="price-value">${number(q?.close,code.startsWith("51")?3:2)}</div><div class="card-bottom"><div><div class="card-caption ${change>0?"up":change<0?"down":""}">${change===null||change===undefined?"等待采样":`${change>0?"+":""}${number(change,2)}% · 观察期`}</div><div class="card-caption">${q?qualities[q.quality][0]:"未采集"}</div></div><div class="spark">${q?.trail?.length?lineSvg(q.trail,{width:110,height:30,compact:true}):""}</div></div></article>`;
}

function renderOverview() {
  $("index-cards").innerHTML=[["000300.SH","沪深300"],["000905.SH","中证500"],["000016.SH","上证50"],["000852.SH","中证1000"]].map(([s,n])=>quoteCard(bySymbol(s),n,s)).join("");
  renderMarket();
  const rows=curve("IC","overview-curve",160);
  $("curve-note").textContent=rows.length?`${rows.length} 个具体合约 · 缓存和接收状态见行情表` : "暂无 IC 具体合约；可在数据页采集 IC00—03。";
  renderSelected();
  $("factor-cards").innerHTML=(state?.formulas||[]).filter(f=>f.enabled).map(f=>{
    const r=f.result||{},entries=Object.entries(r.values||{}),first=entries[0];
    return `<article class="factor-card"><div class="factor-card-top"><h3>${esc(f.name)}</h3>${badge(r.quality)}</div>${r.error?`<div class="metric-error">${esc(r.error)}</div>`:`<div class="metric-number">${number(first?.[1],3)} <span class="muted">${esc(f.unit)}</span></div><div class="metric-label">${esc(first?.[0]||"等待计算")}${entries.length>1?` · 另 ${entries.length-1} 项`:""}</div>`}<div class="metric-meta">${esc(f.id)} · v${esc(f.version.slice(0,6))}<br>${r.calculated_at?shortTime(r.calculated_at):"等待输入"} <button class="text-button" data-edit="${esc(f.id)}">查看公式 ↗</button></div></article>`;
  }).join("") || '<div class="chart-empty full-span">暂无启用的公式。到公式中心发布你的第一个指标。</div>';
}
function renderMarket() {
  const search=$("market-search").value.trim().toLowerCase();
  const all=uniqueQuotes();
  const rows=all.filter(q=>(filter==="全部"||q.category===filter)&&`${q.symbol} ${q.name} ${q.source_symbol}`.toLowerCase().includes(search));
  $("quote-count").textContent=String(all.length);
  $("market-body").innerHTML=rows.map(q=>`<tr data-symbol="${esc(q.symbol)}" class="${q.symbol===selected?"selected":""}"><td><strong>${esc(q.name)}</strong><small>${esc(q.source_symbol)} · ${esc(q.category)}</small></td><td class="number">${number(q.close,q.category==="ETF"?3:2)}</td><td class="number ${q.observed_change>0?"up":q.observed_change<0?"down":""}">${q.observed_change>0?"+":""}${number(q.observed_change,2)}${q.observed_change==null?"":"%"}</td><td class="number">${number(q.volume,0)}<small>${q.volume_interval_seconds?number(q.volume_interval_seconds,2)+" 秒":"无有效区间"}</small></td><td class="number">${number(q.spread,q.category==="ETF"?3:2)}</td><td>${badge(q.quality)}</td></tr>`).join("")||'<tr><td colspan="6" class="empty-cell">没有符合条件的行情<small>选择已有行情目录，或到「数据与任务」采集一轮。</small></td></tr>';
  $("market-time").textContent=state?.updated_at?`后台读取 ${shortTime(state.updated_at)}`:"等待数据";
}
function renderSelected() {
  const q=bySymbol(selected)||uniqueQuotes()[0];
  if(!q){$("selected-chart").innerHTML='<div class="chart-empty">点击行情行查看细节</div>';$("selected-details").innerHTML="";return;}
  selected=q.symbol;
  $("selected-name").textContent=q.name;$("selected-code").textContent=`${q.source_symbol} · 采集时刻轨迹`;$("selected-quality").innerHTML=badge(q.quality);
  $("selected-chart").innerHTML=lineSvg(q.trail||[],{height:110});
  $("selected-details").innerHTML=[["买一 / 数量",`${number(q.bid_price_1,3)} / ${number(q.bid_volume_1,0)}`],["卖一 / 数量",`${number(q.ask_price_1,3)} / ${number(q.ask_volume_1,0)}`],["接口时分秒",q.quote_time||"未提供"],["交易日",q.trading_date||"接口未提供"]].map(([label,value])=>`<div><span>${label}</span><strong>${esc(value)}</strong></div>`).join("");
}
function renderFutures() {
  const rows=curveRows(root);
  $("futures-cards").innerHTML=rows.length?rows.map(q=>quoteCard(q,q.source_symbol.replace(".CFE",""),q.source_symbol)).join(""):'<div class="chart-empty full-span">尚无此品种的具体合约行情</div>';
  curve(root,"futures-curve",280);
  const pairs=[];
  for(let i=0;i<rows.length;i++)for(let j=i+1;j<rows.length;j++){
    const n=rows[i],f=rows[j],aligned=Math.abs(Date.parse(n.timestamp)-Date.parse(f.timestamp))<=Number(config.max_skew_seconds)*1000;
    const usable=aligned&&n.mid!==null&&f.mid!==null;
    pairs.push(`<tr><td><strong>${esc(n.source_symbol.match(/\d{4}/)[0])} / ${esc(f.source_symbol.match(/\d{4}/)[0])}</strong><small>${aligned?"盘口观察值":"采集时间不齐"}</small></td><td class="number">${aligned?number(n.close-f.close,2):"—"}</td><td class="number">${usable?number(n.ask_price_1-f.bid_price_1,2):"—"}</td><td class="number">${usable?number(n.bid_price_1-f.ask_price_1,2):"—"}</td></tr>`);
  }
  $("spread-body").innerHTML=pairs.join("")||'<tr><td colspan="4" class="empty-cell">至少需要两个合约</td></tr>';
  $("mapping-list").innerHTML=[0,1,2,3].map(i=>{const alias=`${root}0${i}.CFE`,q=bySymbol(alias);return `<div class="mapping-item">${alias}<span class="arrow">→</span><strong>${esc(q?.source_symbol||"待解析")}</strong><small>第 ${i+1} 个到期月份 · ${esc(q?.trading_date||"等待行情")}</small></div>`;}).join("");
}
function renderPublished() {
  $("published-list").innerHTML=(state?.formulas||[]).map(f=>`<div class="published"><div><button class="text-button" data-edit="${esc(f.id)}">${esc(f.name)}</button><small>v${esc(f.version.slice(0,6))}</small></div><button class="toggle" data-toggle="${esc(f.id)}" data-enabled="${!f.enabled}">${f.enabled?"停用":"启用"}</button></div>`).join("");
}
function fillFormula(spec) {
  $("formula-name").value=spec.name;$("formula-id").value=spec.id;$("formula-symbols").value=spec.symbols.join(", ");$("formula-params").value=JSON.stringify(spec.params,null,2);$("formula-code").value=spec.code;$("formula-unit").value=spec.unit;
  $("editor-version").textContent=spec.version?`已发布 v${spec.version.slice(0,6)}`:"模板草稿";$("preview-values").innerHTML='<p class="muted">点击试算，用当前行情检查结果。</p>';$("preview-quality").textContent="尚未试算";errorAt("formula-error","");
  document.querySelectorAll(".template").forEach(el=>el.classList.toggle("active",el.dataset.template===spec.id));
}
function formulaValue() {
  let params;
  try{params=JSON.parse($("formula-params").value);}catch{throw new Error("参数不是有效的 JSON 对象");}
  return {id:$("formula-id").value.trim(),name:$("formula-name").value.trim(),symbols:$("formula-symbols").value,params,code:$("formula-code").value,unit:$("formula-unit").value.trim(),enabled:true};
}
function fillSettings() {
  for(const [id,key] of [["market-root","market_root"],["results-root","results_root"],["interval","interval"],["max-age","max_age_seconds"],["max-skew","max_skew_seconds"],["mapping-file","mapping_file"],["calendar-file","calendar_file"]])$(id).value=config[key];
  $("symbols").value=config.symbols.join("\n");
  $("old-roots").innerHTML=(config.previous_result_roots||[]).map(p=>`<div class="old-root">保留的历史结果目录<br>${esc(p)}</div>`).join("");
}
function settingsValue() {
  return {market_root:$("market-root").value,results_root:$("results-root").value,interval:Number($("interval").value),max_age_seconds:Number($("max-age").value),max_skew_seconds:Number($("max-skew").value),mapping_file:$("mapping-file").value,calendar_file:$("calendar-file").value,symbols:$("symbols").value};
}
function renderCollection() {
  const c=state?.collection||{},active=["starting","running","stopping"].includes(c.status);
  const names={idle:"未启动",starting:"正在启动",running:"采集中",stopping:"正在停止",stopped:"已停止",failed:"启动 / 采集失败"};
  $("collect-badge").textContent=`采集 · ${names[c.status]||"未知"}`;$("collect-badge").className=`badge ${active?"teal":c.status==="failed"?"red":"neutral"}`;
  $("collection-summary").innerHTML=`<div><span>任务状态</span><strong>${names[c.status]||"—"}</strong></div><div><span>已采集轮数</span><strong>${number(c.polls,0)}</strong></div><div><span>保存行情行数（含别名）</span><strong>${number(c.quotes_saved,0)}</strong></div><div><span>采集间隔</span><strong>${number(config.interval,1)} 秒</strong></div>${c.error?`<div class="error-box full-span">${esc(c.error)}</div>`:""}`;
  $("start-collection").disabled=active;$("once-collection").disabled=active;$("stop-collection").disabled=!active||c.status==="stopping";
  $("collection-log").innerHTML=(c.logs||[]).slice().reverse().map(l=>`<div class="log-item"><time>${shortTime(l.time)}</time>${esc(l.message)}</div>`).join("")||'<div class="log-item">尚未由本看板发起采集；已有行情仍可只读查看。</div>';
}

function render() {
  errorAt("global-error",state?.error);
  $("last-update").textContent=state?.updated_at?`后台读取 ${fullTime(state.updated_at)} · 北京时间`:"等待后台读取";
  renderCollection();
  if(page==="overview")renderOverview();
  if(page==="futures")renderFutures();
  if(page==="formulas")renderPublished();
}
const pageInfo={overview:["市场总览","MARKET OVERVIEW","看见变化，追踪依据。","关联期货、指数与 ETF，把每一次观察留下来。"],futures:["期货结构","FUTURES STRUCTURE","在期限之间，观察定价。","同时查看价格曲线、跨期价差与实际合约身份。"],formulas:["公式中心","FORMULA WORKSPACE","把你的判断，变成指标。","编辑受限 Python 模板，试算后发布到看板。"],archive:["结果与回放","RESEARCH ARCHIVE","留下数值，也留下依据。","按交易日回看计算结果，核对输入和当时的公式版本。"],settings:["数据与任务","DATA & OPERATIONS","让数据持续、有序地流动。","选择行情目录，管理订阅与独立的看板结果。"]};
function navigate(next) {
  page=next;const info=pageInfo[next];
  document.querySelectorAll(".page").forEach(el=>el.hidden=el.id!==`page-${next}`);
  document.querySelectorAll(".nav-item").forEach(el=>el.classList.toggle("active",el.dataset.page===next));
  ["breadcrumb","eyebrow","page-title","page-subtitle"].forEach((id,i)=>$(id).textContent=info[i]);
  render();if(next==="archive")loadHistory();window.scrollTo({top:0,behavior:"instant"});
}
async function refresh() {
  if(loading)return;
  loading=true;
  try{state=await api("/api/state");connected=true;$("connection-light").className="status-light online";$("connection-text").textContent="本机服务已连接";render();}
  catch(error){connected=false;$("connection-light").className="status-light";$("connection-text").textContent="服务连接中断";errorAt("global-error",`连接中断，页面保留最后一次结果：${error.message}`);}
  finally{loading=false;}
}
async function loadHistory() {
  try{
    const result=await api(`/api/history?day=${encodeURIComponent($("history-day").value)}`);historyRows=result.rows;
    $("archive-stats").innerHTML=[["保存的计算记录",result.storage.rows],["已发布 Parquet 分片",result.storage.parts],["待归档记录",result.storage.pending||0]].map(([label,value])=>`<div class="stat-tile"><span>${label}</span><strong>${number(value,0)}</strong></div>`).join("");
    $("history-body").innerHTML=historyRows.map((r,i)=>`<tr data-record="${i}"><td>${shortTime(r.calculated_at)}<small>${esc(r.calculated_at.slice(0,10))}</small></td><td><strong>${esc(r.name)}</strong><small>${esc(r.factor_id)} · v${esc(r.version.slice(0,6))}</small></td><td>${esc(r.trade_date)}</td><td>${Object.entries(r.values).map(([k,v])=>`${esc(k)} ${number(v,3)}`).join("<br>")}</td><td>${badge(r.quality)}</td><td><span class="badge ${r.archived?"teal":"neutral"}">${r.archived?"已归档":"实时库"}</span></td></tr>`).join("")||'<tr><td colspan="6" class="empty-cell">此交易日暂无计算记录<small>可清空日期查看全部记录。</small></td></tr>';
  }catch(error){toast(error.message);}
}

document.addEventListener("click",async event=>{
  const nav=event.target.closest("[data-page],[data-go]");if(nav){navigate(nav.dataset.page||nav.dataset.go);return;}
  const tab=event.target.closest("[data-filter]");if(tab){filter=tab.dataset.filter;document.querySelectorAll("[data-filter]").forEach(el=>el.classList.toggle("active",el===tab));renderMarket();return;}
  const row=event.target.closest("[data-symbol]");if(row){selected=row.dataset.symbol;renderMarket();renderSelected();return;}
  const rootTab=event.target.closest("[data-root]");if(rootTab){root=rootTab.dataset.root;document.querySelectorAll("[data-root]").forEach(el=>el.classList.toggle("active",el===rootTab));renderFutures();return;}
  const template=event.target.closest("[data-template]");if(template){fillFormula(templates.find(t=>t.id===template.dataset.template));return;}
  const edit=event.target.closest("[data-edit]");if(edit){navigate("formulas");fillFormula(state.formulas.find(f=>f.id===edit.dataset.edit));return;}
  const toggle=event.target.closest("[data-toggle]");if(toggle){try{await api("/api/formulas/toggle",{id:toggle.dataset.toggle,enabled:toggle.dataset.enabled==="true"});await refresh();toast("公式状态已更新");}catch(error){toast(error.message);}return;}
  const record=event.target.closest("[data-record]");if(record){const r=historyRows[Number(record.dataset.record)];$("dialog-title").textContent=`${r.name} · v${r.version.slice(0,6)}`;$("dialog-content").innerHTML=`<p>计算于 ${fullTime(r.calculated_at)}。${qualities[r.quality]?.[0]||"观察记录"}；输入时间不代表已认证的交易所事件时间。</p><pre>${esc(JSON.stringify({values:r.values,inputs:r.inputs,version:r.version,trade_date:r.trade_date},null,2))}</pre>`;$("detail-dialog").showModal();}
});
$("close-dialog").onclick=()=>$("detail-dialog").close();
$("market-search").addEventListener("input",renderMarket);
$("refresh").onclick=()=>refresh();
$("preview-formula").onclick=async()=>{
  const button=$("preview-formula");button.disabled=true;errorAt("formula-error","");
  try{const result=await api("/api/formulas/preview",formulaValue());$("preview-quality").innerHTML=badge(result.quality);$("preview-values").innerHTML=Object.entries(result.values).map(([key,value])=>`<div class="preview-value"><span>${esc(key)}</span><strong>${number(value,4)}</strong> <span>${esc(result.unit)}</span></div>`).join("");}
  catch(error){errorAt("formula-error",error.message);$("preview-quality").textContent="试算失败";$("preview-values").innerHTML="";}
  finally{button.disabled=false;}
};
$("formula-form").onsubmit=async event=>{
  event.preventDefault();const button=$("publish-formula");button.disabled=true;errorAt("formula-error","");
  try{const result=await api("/api/formulas/publish",formulaValue());$("editor-version").textContent=`已发布 v${result.formula.version.slice(0,6)}`;toast("公式已发布并加入总览；输入标的已加入本看板的采集清单。");await refresh();}
  catch(error){errorAt("formula-error",error.message);}finally{button.disabled=false;}
};
$("formula-code").addEventListener("keydown",event=>{if(event.key==="Tab"){event.preventDefault();const el=event.target,start=el.selectionStart,end=el.selectionEnd;el.setRangeText("    ",start,end,"end");}});
$("settings-form").onsubmit=async event=>{
  event.preventDefault();errorAt("settings-error","");
  try{const result=await api("/api/config",settingsValue());config=result.config;fillSettings();toast("设置已保存。历史数据保留在原目录。");await refresh();}
  catch(error){errorAt("settings-error",error.message);}
};
async function startCollection(once) {
  errorAt("settings-error","");
  try{const result=await api("/api/config",settingsValue());config=result.config;fillSettings();await api("/api/collection/start",{once});toast(once?"已发起一轮采集":"已启动采集，关闭页面不停止任务。");await refresh();}
  catch(error){errorAt("settings-error",error.message);}
}
$("start-collection").onclick=()=>startCollection(false);$("once-collection").onclick=()=>startCollection(true);
$("stop-collection").onclick=async()=>{try{await api("/api/collection/stop",{});toast("停止请求已发送，正在完成当前批次。");await refresh();}catch(error){toast(error.message);}};
$("load-universe").onclick=async()=>{try{const u=await api("/api/universe");$("universe-note").textContent=`${u.trading_date} · ${u.basis} · ${u.contracts[root].join(" / ")}`;}catch(error){toast(error.message);}};
$("history-search").onclick=loadHistory;
$("flush-results").onclick=async()=>{try{await api("/api/results/flush",{});await loadHistory();toast("已发布全部待归档结果。");}catch(error){toast(error.message);}};
$("shutdown").onclick=async()=>{try{await api("/api/shutdown",{});toast("正在停止后台任务并归档；可使用启动脚本重新打开。");}catch(error){toast(error.message);}};

async function boot() {
  try{
    const initial=await api("/api/bootstrap");token=initial.token;config=initial.config;templates=initial.templates;state=initial.state;
    fillSettings();$("template-list").innerHTML=templates.map(t=>`<button class="template" data-template="${esc(t.id)}"><span class="template-icon">↗</span><strong>${esc(t.name)}</strong><small>${esc(t.description)}</small></button>`).join("");fillFormula(templates[0]);render();await refresh();
  }catch(error){errorAt("global-error",`看板初始化失败：${error.message}`);}
  const poll=async()=>{await refresh();setTimeout(poll,2500);};setTimeout(poll,2500);
}
function updateClock() {$("clock").textContent=new Date().toLocaleString("zh-CN",{timeZone:"Asia/Shanghai",hour12:false});}
updateClock();setInterval(updateClock,1000);
boot();
