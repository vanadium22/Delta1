"use strict";
const $ = (id) => document.getElementById(id);
const state = {kind:"swap", date:"", sheet:"", catalog:null, columns:[], filters:[], visible:[],
  result:null, page:1, pageSize:50, sort:null, epsilon:1e-8, search:"", requestId:0, loading:false, sheetRequest:0};
const defaultNames = {
  swap:["交易确认书编号","交易对手名称","标的物代码","标的物名称","我方资产方向","标的名义数量","标的名义本金额","计息费率","起始日","期末观察日","标的估值价格","交易货币"],
  review:["协议编号","交易对手","标的","互换类型","交易起始日","交易结算日","起始价格","股数","利率","币种","起始/结算价是否在收盘价8%变动区间内","期初/结算汇率是否在当前汇率10%变动区间内","操作人员"]
};
let debounceTimer, toastTimer, syncTimer;
function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function option(value, label) { const node=element("option","",label);node.value=value;return node; }
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "请求失败，请重试。");
  return result;
}
function toast(message) { $("toast").textContent=message;$("toast").hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$("toast").hidden=true,4500); }
function setSettingsMessage(message,error=false) {$("settings-message").textContent=message;$("settings-message").hidden=!message;$("settings-message").classList.toggle("error",error);}
function notice(message,error=false) {$("source-notice").textContent=message;$("source-notice").hidden=!message;$("source-notice").classList.toggle("error",error);}
function savedKey() { return "d1-columns:"+state.kind+":"+state.sheet; }
function chooseVisible() {
  const ids=new Set(state.columns.map(c=>c.id));let saved;
  try {saved=JSON.parse(localStorage.getItem(savedKey()));} catch {}
  state.visible=Array.isArray(saved)?saved.filter(id=>ids.has(id)):[];
  if (!state.visible.length) defaultVisible();
}
function defaultVisible() {
  state.visible=state.columns.filter(c=>defaultNames[state.kind].includes(c.name)).map(c=>c.id);
  if (state.visible.length<3) state.visible=state.columns.slice(0,12).map(c=>c.id);
}
function persistVisible() {try {localStorage.setItem(savedKey(),JSON.stringify(state.visible));}catch{}}
function setBusy(busy) {state.loading=busy;$("loading").hidden=!busy;$("report-table").setAttribute("aria-busy",String(busy));}
function resetQuery() {
  clearTimeout(debounceTimer);state.requestId++;
  state.search="";$("global-search").value="";state.filters=[];state.sort=null;state.page=1;
  state.result=null;state.columns=[];state.visible=[];$("filter-list").replaceChildren();$("query-error").hidden=true;
  $("report-table").querySelector("tbody").replaceChildren();$("report-table").querySelector("thead").replaceChildren();
}
function defaultFilter() {
  const column=state.columns.find(c=>["交易对手名称","交易对手"].includes(c.name))||state.columns.find(c=>c.type==="text");
  if(column)state.filters.push({column:column.id,op:"fuzzy",value:""});
}
async function refreshCatalog(preferredDate) {
  state.catalog=await api("/api/catalog");
  state.epsilon=state.catalog.settings.epsilon;$("epsilon").value=String(state.epsilon);
  const dates=state.catalog.dates.filter(item=>item.files[state.kind]);
  $("report-date").replaceChildren(...dates.map(item=>option(item.date,item.date+(item.complete?"":" · 文件未齐"))));
  state.date=dates.some(item=>item.date===preferredDate)?preferredDate:(dates[0]?.date||"");
  if (state.date) $("report-date").value=state.date;
  await loadSheets();
}
function updateProvenance() {
  const dataset=state.catalog.dates.find(item=>item.date===state.date);
  const file=dataset?.files[state.kind];
  $("dataset-origin").replaceChildren(element("span","origin-dot"),document.createTextNode(file?.origin||"等待本地数据"));
  $("file-caption").textContent=file?.name||"尚未保存报表";$("file-caption").title=file?.path||"";
  if (!file) notice("尚未保存日报。请设置共享来源并同步，或导入已有 Excel。");
  else if (!dataset.complete) notice(state.date+" 目前仅保存了一份报表，请补齐同日期的另一份文件。");
  else if (file.origin!=="共享目录下载") notice("当前显示 "+state.date+" 的"+file.origin+"。尚未通过共享目录核实前一交易日报表，请连接公司网络后同步。");
  else notice("当前显示 "+state.date+" 报表。来源为共享目录下载；同步按早于今日的最新日期目录选择。");
}
async function loadSheets() {
  const sheetRequest=++state.sheetRequest;resetQuery();updateProvenance();
  $("page-title").textContent=state.kind==="swap"?"存续合约查询":"簿记要素复核";
  $("page-description").textContent=state.kind==="swap"?"按交易对手、标的和交易要素，快速找到需要的记录。":"查询簿记明细、价格与汇率检查结果，逐项查看交易要素。";
  document.querySelectorAll("[data-kind]").forEach(button=>button.classList.toggle("active",button.dataset.kind===state.kind));
  if (!state.date) {
    setBusy(false);$("report-date").replaceChildren(option("","无本地报表"));$("report-sheet").replaceChildren(option("","等待导入"));
    $("table-title").textContent=state.catalog.reports[state.kind].sheet;
    renderEmpty("尚未保存日报","连接共享目录后同步，或在「数据与同步」中导入已有 Excel。",true);
    $("result-count").textContent="0 条记录";$("record-range").textContent="—";$("page-number").textContent="1 / 1";
    $("column-count").textContent="";$("prev-page").disabled=true;$("next-page").disabled=true;
    return;
  }
  setBusy(true);
  try {
    const data=await api("/api/sheets?kind="+encodeURIComponent(state.kind)+"&date="+encodeURIComponent(state.date));
    if(sheetRequest!==state.sheetRequest)return;
    state.sheet=data.default_sheet;$("report-sheet").replaceChildren(...data.sheets.map(name=>option(name,name)));$("report-sheet").value=state.sheet;
    await query(true);
  }catch(error){if(sheetRequest===state.sheetRequest){showQueryError(error.message);setBusy(false);}}
}
function renderEmpty(title,description,setup=false) {
  $("empty-state").hidden=false;$("table-scroll").hidden=true;
  $("empty-state").querySelector("h3").textContent=title;$("empty-state").querySelector("p").textContent=description;
  $("empty-reset").textContent=setup?"数据与同步":"清空筛选";$("empty-reset").dataset.setup=String(setup);
}
function showQueryError(message) {
  $("query-error").textContent=message;$("query-error").hidden=false;$("table-scroll").hidden=true;$("empty-state").hidden=true;
  $("result-count").textContent="查询未完成";$("record-range").textContent="请调整条件后重试";
  $("prev-page").disabled=true;$("next-page").disabled=true;
}
async function query(first=false) {
  if (!state.date||!state.sheet)return;
  const requestId=++state.requestId;setBusy(true);$("query-error").hidden=true;
  try {
    const data=await api("/api/query",{kind:state.kind,date:state.date,sheet:state.sheet,filters:state.filters,epsilon:$("epsilon").value,
      search:state.search,page:state.page,page_size:state.pageSize,sort:state.sort});
    if(requestId!==state.requestId)return;
    state.result=data;state.columns=data.columns;state.page=data.page;
    if(first){chooseVisible();defaultFilter();renderFilters();}
    renderTable();
  }catch(error){if(requestId===state.requestId)showQueryError(error.message);}
  finally{if(requestId===state.requestId)setBusy(false);}
}
function scheduleQuery() {state.page=1;clearTimeout(debounceTimer);debounceTimer=setTimeout(()=>query(),320);}
function operators(column) {
  const common=[["blank","为空"],["not_blank","不为空"]];
  if(column.type==="number")return [["range","范围（含边界）"],["gt","大于 >"],["gte","大于等于 ≥"],["lt","小于 <"],["lte","小于等于 ≤"],["eq","近似等于 ≈"],["ne","不等于 ≠"],["zero","近似为零 |x| ≤ ε"],["nonzero","非零 |x| > ε"],...common];
  if(column.type==="date")return [["range","日期范围"],["eq","等于"],["gte","不早于"],["lte","不晚于"],...common];
  return [["fuzzy","模糊匹配 · 支持简称"],["contains","连续包含"],["eq","精确等于"],["ne","不等于"],...common];
}
function renderFilters() {
  $("filter-list").replaceChildren();
  state.filters.forEach((filter,idx)=>{
    const column=state.columns.find(c=>c.id===filter.column);if(!column)return;
    const row=element("div","filter-row");
    const col=element("select","filter-column");col.setAttribute("aria-label","筛选列 "+(idx+1));
    col.append(...state.columns.map(c=>option(c.id,(c.type==="number"?"#  ":c.type==="date"?"▦  ":"")+c.name)));col.value=filter.column;
    col.addEventListener("change",()=>{
      const selected=state.columns.find(c=>c.id===col.value);
      state.filters[idx]={column:col.value,op:selected.type==="text"?"fuzzy":"range",value:"",min:"",max:""};
      renderFilters();scheduleQuery();
    });
    const op=element("select","filter-operator");op.setAttribute("aria-label","筛选方式 "+(idx+1));op.append(...operators(column).map(([key,label])=>option(key,label)));op.value=filter.op;
    op.addEventListener("change",()=>{filter.op=op.value;filter.value="";filter.min="";filter.max="";renderFilters();scheduleQuery();});
    row.append(col,op);
    if(["zero","nonzero","blank","not_blank"].includes(filter.op)) {
      row.append(element("div","no-value",filter.op==="zero"?"绝对值在 ε 以内，空值不计入":filter.op==="nonzero"?"绝对值大于 ε，空值不计入":"无需填写值"));
    } else if(filter.op==="range") {
      const values=element("div","filter-values");
      ["min","max"].forEach((key,i)=>{
        if(i)values.append(element("span","","至"));
        const input=element("input");input.type=column.type==="date"?"date":"text";input.value=filter[key]||"";
        input.placeholder=i?"上限（可留空）":"下限（可留空）";input.setAttribute("aria-label",(i?"上限 ":"下限 ")+(idx+1));
        if(column.type==="number")input.inputMode="decimal";
        input.addEventListener("input",()=>{filter[key]=input.value;scheduleQuery();});values.append(input);
      });row.append(values);
    } else {
      const input=element("input","filter-value");input.type=column.type==="date"?"date":"text";input.value=filter.value||"";
      input.placeholder=column.type==="text"?"输入关键词，例如：申万 / 证投":column.percent?"输入原始小数或百分号，例如 0.05 或 5%":"输入数值，支持 1e-8、千分位";
      input.autocomplete="off";input.setAttribute("aria-label","筛选值 "+(idx+1));if(column.type==="number")input.inputMode="decimal";
      input.addEventListener("input",()=>{filter.value=input.value;scheduleQuery();});row.append(input);
    }
    const remove=element("button","filter-remove","×");remove.setAttribute("aria-label","删除条件 "+(idx+1));
    remove.addEventListener("click",()=>{state.filters.splice(idx,1);renderFilters();scheduleQuery();});row.append(remove);
    $("filter-list").append(row);
  });
}
function formatValue(value,column) {
  if(value===null||value===undefined||String(value).trim()==="")return "—";
  if(column.type!=="number"||typeof value!=="number")return String(value);
  if(column.percent)return new Intl.NumberFormat("zh-CN",{style:"percent",maximumFractionDigits:8}).format(value);
  if(Math.abs(value)>0&&Math.abs(value)<0.000001)return value.toExponential(6).replace(/\.?0+e/,"e");
  return new Intl.NumberFormat("zh-CN",{maximumFractionDigits:10,maximumSignificantDigits:15}).format(value);
}
function valueNode(value,column) {
  const text=formatValue(value,column);
  if(column.name.includes("是否")&&["是","否"].includes(text))return element("span",text==="是"?"flag":"flag bad",text);
  return element("span",text==="—"?"text-missing":"",text);
}
function renderTable() {
  const result=state.result;if(!result)return;
  const selected=state.columns.map((column,index)=>({column,index})).filter(item=>state.visible.includes(item.column.id));
  const table=$("report-table");const head=table.querySelector("thead"),body=table.querySelector("tbody");
  head.replaceChildren();body.replaceChildren();const tr=element("tr");tr.append(element("th","row-number","#"));
  selected.forEach(({column},idx)=>{
    const sorted=state.sort?.column===column.id;
    const th=element("th",[column.type==="number"?"numeric":"",idx===0?"sticky-col":"",sorted?"sorted":""].join(" "));
    th.setAttribute("scope","col");if(sorted)th.setAttribute("aria-sort",state.sort.direction==="asc"?"ascending":"descending");
    const button=element("button","",column.name);button.append(element("span","sort-arrow",sorted?(state.sort.direction==="asc"?"↑":"↓"):"↕"));
    button.title="按 "+column.name+" 排序";button.addEventListener("click",()=>{state.sort={column:column.id,direction:sorted&&state.sort.direction==="asc"?"desc":"asc"};state.page=1;query();});
    th.append(button);tr.append(th);
  });head.append(tr);
  result.rows.forEach((record,offset)=>{
    const row=element("tr");row.tabIndex=0;row.setAttribute("aria-label","查看 Excel 第 "+record.excel_row+" 行详情");
    row.append(element("td","row-number",String((state.page-1)*state.pageSize+offset+1)));
    selected.forEach(({column,index},idx)=>{
      const cell=element("td",[column.type==="number"?"numeric":"",idx===0?"sticky-col record-id":""].join(" "));
      cell.title=record.values[index]==null?"空值":String(record.values[index]);cell.append(valueNode(record.values[index],column));row.append(cell);
    });
    row.addEventListener("click",()=>openDetails(record));
    row.addEventListener("keydown",(event)=>{if(event.key==="Enter"){event.preventDefault();openDetails(record);}});
    body.append(row);
  });
  $("table-title").textContent=state.sheet;
  $("result-count").textContent="匹配 "+result.matched.toLocaleString()+" / 共 "+result.total.toLocaleString()+" 条";
  $("column-count").textContent=selected.length+"/"+state.columns.length;
  $("table-scroll").hidden=!result.matched;$("empty-state").hidden=!!result.matched;
  if(!result.matched)renderEmpty("没有匹配的记录","试试缩短关键词，或调整列筛选条件。");
  $("page-number").textContent=result.page+" / "+result.pages;
  $("prev-page").disabled=result.page<=1;$("next-page").disabled=result.page>=result.pages;
  const start=result.matched?(result.page-1)*result.page_size+1:0;
  $("record-range").textContent="显示 "+start.toLocaleString()+"–"+Math.min(result.page*result.page_size,result.matched).toLocaleString()+" 条";
  $("query-error").hidden=true;
}
function clearFilters() {state.search="";$("global-search").value="";state.filters=[];defaultFilter();renderFilters();state.page=1;query();}
function openDetails(record) {
  $("detail-caption").textContent=state.date+" · "+state.sheet+" · Excel 第 "+record.excel_row+" 行";
  $("detail-fields").replaceChildren();
  state.columns.forEach((column,idx)=>{
    const field=element("div","detail-field");field.append(element("dt","",column.name));
    field.append(element("dd",column.type==="number"?"numeric":"",record.values[idx]==null?"—":String(record.values[idx])));
    $("detail-fields").append(field);
  });$("detail-dialog").showModal();
}
function openSettings() {
  const settings=state.catalog?.settings||{};$("source-root").value=settings.source_root||"";$("data-dir").value=settings.data_dir||"data/reports";
  $("resolved-path").textContent=state.catalog?.saved_dir||"";setSettingsMessage("");$("settings-dialog").showModal();
}
function renderColumnOptions() {
  $("column-options").replaceChildren();
  state.columns.forEach(column=>{
    const label=element("label"),check=element("input");check.type="checkbox";check.checked=state.visible.includes(column.id);
    check.addEventListener("change",()=>{
      if(!check.checked&&state.visible.length===1){check.checked=true;toast("请至少保留一列。");return;}
      state.visible=check.checked?[...state.visible,column.id]:state.visible.filter(id=>id!==column.id);persistVisible();renderTable();
    });label.append(check,document.createTextNode(column.name));$("column-options").append(label);
  });
}
function syncBusy(busy) {$("sync-button").disabled=busy;$("sync-button").lastElementChild.textContent=busy?"正在同步…":"同步前一交易日";}
async function pollSync() {
  try {
    const job=await api("/api/sync");
    if(job.state==="running"){syncBusy(true);syncTimer=setTimeout(pollSync,1100);return;}
    syncBusy(false);
    if(job.state==="success"){await refreshCatalog(job.result.date);toast("已保存 "+job.result.date+" 的两份日报");}
    if(job.state==="error"){notice(job.error,true);toast("同步未完成，本地报表仍可查询。");}
  }catch(error){syncBusy(false);notice(error.message,true);}
}
document.querySelectorAll("[data-kind]").forEach(button=>button.addEventListener("click",async()=>{
  if(state.kind===button.dataset.kind)return;state.requestId++;state.kind=button.dataset.kind;
  try{await refreshCatalog(state.date);}catch(error){showQueryError(error.message);}
}));
$("report-date").addEventListener("change",()=>{state.requestId++;state.date=$("report-date").value;loadSheets().catch(error=>showQueryError(error.message));});
$("report-sheet").addEventListener("change",()=>{state.requestId++;resetQuery();state.sheet=$("report-sheet").value;query(true);});
$("global-search").addEventListener("input",()=>{state.search=$("global-search").value;scheduleQuery();});
$("epsilon").addEventListener("input",scheduleQuery);$("clear-filters").addEventListener("click",clearFilters);
$("empty-reset").addEventListener("click",()=>{$("empty-reset").dataset.setup==="true"?openSettings():clearFilters();});
$("add-filter").addEventListener("click",()=>{
  if(!state.columns.length){toast("请先读取一份报表。");return;}if(state.filters.length>=30){toast("最多可组合 30 个条件。");return;}
  const used=new Set(state.filters.map(f=>f.column));const column=state.columns.find(c=>!used.has(c.id))||state.columns[0];
  state.filters.push({column:column.id,op:column.type==="text"?"fuzzy":"range",value:"",min:"",max:""});renderFilters();
});
$("page-size").addEventListener("change",()=>{state.pageSize=Number($("page-size").value);state.page=1;query();});
$("prev-page").addEventListener("click",()=>{state.page--;query();$("table-scroll").scrollTop=0;});
$("next-page").addEventListener("click",()=>{state.page++;query();$("table-scroll").scrollTop=0;});
$("open-settings").addEventListener("click",openSettings);$("side-settings").addEventListener("click",openSettings);
document.querySelectorAll(".close-dialog").forEach(b=>b.addEventListener("click",()=>$("settings-dialog").close()));
$("settings-form").addEventListener("submit",async(event)=>{
  event.preventDefault();$("save-settings").disabled=true;setSettingsMessage("");
  try {
    await api("/api/settings",{source_root:$("source-root").value,data_dir:$("data-dir").value,epsilon:$("epsilon").value});
    await refreshCatalog(state.date);$("resolved-path").textContent=state.catalog.saved_dir;
    setSettingsMessage("设置已保存并生效。连接公司网络后可点击「同步前一交易日」。");toast("设置已保存");
  }catch(error){setSettingsMessage(error.message,true);}finally{$("save-settings").disabled=false;}
});
$("sync-button").addEventListener("click",async()=>{
  if(!state.catalog?.settings.source_root){openSettings();setSettingsMessage("请填写共享来源目录并保存后同步。");return;}
  syncBusy(true);clearTimeout(syncTimer);
  try{await api("/api/sync",{});pollSync();}catch(error){syncBusy(false);notice(error.message,true);}
});
$("import-button").addEventListener("click",()=>$("import-files").click());
$("import-files").addEventListener("change",async()=>{
  const files=[...$("import-files").files];if(!files.length)return;
  $("import-button").disabled=true;let preferredDate;
  try {
    for(const file of files) {
      setSettingsMessage("正在保存 "+file.name+"…");
      const response=await fetch("/api/import",{method:"POST",headers:{"Content-Type":"application/octet-stream","X-Filename":encodeURIComponent(file.name)},body:file});
      const result=await response.json();if(!response.ok)throw new Error(result.error||"导入失败");preferredDate=result.date;
    }
    await refreshCatalog(preferredDate);setSettingsMessage("已保存 "+files.length+" 份文件。实际位置："+state.catalog.saved_dir);toast("本地报表已导入");
  }catch(error){setSettingsMessage(error.message,true);try{await refreshCatalog(preferredDate);}catch{}}
  finally{$("import-button").disabled=false;$("import-files").value="";}
});
$("column-button").addEventListener("click",()=>{if(!state.columns.length)return;renderColumnOptions();$("columns-dialog").showModal();});
document.querySelectorAll(".close-columns").forEach(b=>b.addEventListener("click",()=>$("columns-dialog").close()));
$("all-columns").addEventListener("click",()=>{state.visible=state.columns.map(c=>c.id);persistVisible();renderColumnOptions();renderTable();});
$("default-columns").addEventListener("click",()=>{defaultVisible();persistVisible();renderColumnOptions();renderTable();});
$("close-detail").addEventListener("click",()=>$("detail-dialog").close());
document.addEventListener("keydown",(event)=>{
  if(event.key==="/"&&!["INPUT","SELECT","TEXTAREA"].includes(document.activeElement?.tagName)&&!document.querySelector("dialog[open]")){event.preventDefault();$("global-search").focus();}
});
async function start() {
  try {await refreshCatalog();const job=await api("/api/sync");if(job.state==="running")pollSync();}
  catch(error){showQueryError(error.message);notice("本地数据读取失败，请打开「数据与同步」检查目录。",true);setBusy(false);}
}
start();
