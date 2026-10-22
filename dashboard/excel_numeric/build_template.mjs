// Developer-only template authoring. Company runtime needs Python + desktop Excel.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const {Workbook,SpreadsheetFile}=await import(process.env.ARTIFACT_TOOL_MODULE ? pathToFileURL(process.env.ARTIFACT_TOOL_MODULE).href : '@oai/artifact-tool');
const destination=process.argv[2];
if(!destination)throw new Error('Pass the output template.xlsx path');
const metadata=JSON.parse(await fs.readFile(process.argv[3],'utf8'));
const headers={
 '数字看板':['品种','档位','具体合约','期货 F','指数 S','分红 D 点','T 自然日','基差 点','基差 bp','年化 %','数据类型','数据时间（北京）','当前挂牌合约','说明'],
 '分位与样本':['品种','档位','具体合约','窗口','分位 %','有效 n','缺失日','排除日','定位值','单位','定位时间（北京）','参考截止（北京）','说明'],
 '研究指标':['品种','档位','具体合约','指标ID','指标名称','数值','单位','数据类型','数据时间（北京）','可用性说明','口径 / 公式'],
 '来源与状态':['项目','内容'],
};
const wb=Workbook.create();
const {addWorkspace}=await import('./workspace_template.mjs');
addWorkspace(wb,metadata);
Object.assign(headers,metadata.headers);
for(const [name,cols] of Object.entries(headers)){
 const sheet=wb.worksheets.add(name);sheet.showGridLines=false;
 const last=String.fromCharCode(64+cols.length), end=name==='研究指标'?800:name==='指标数据'?406:name==='分位与样本'?80:80;
 const range=sheet.getRange(`A1:${last}${end}`);
 range.format.font={name:'Microsoft YaHei',size:11};range.format.rowHeight=25;range.format.columnWidth=16;
 sheet.getRange('A2').values=[['DELTA1 · '+name]];sheet.getRange('A2').format.font={size:19,bold:true,color:'#12384B'};
 sheet.getRange('A3').values=[['空白模板 · 请用 start_numeric_excel.cmd 打开自动更新版']];
 sheet.getRange('A4').values=[['未连接 · 本模板不含任何公司行情或凭据']];sheet.getRange('A4').format.font.color='#6B7280';
 sheet.getRange(`A6:${last}6`).values=[cols];
 sheet.getRange(`A6:${last}6`).format.fill='#12384B';sheet.getRange(`A6:${last}6`).format.font={bold:true,color:'#FFFFFF'};
 sheet.getRange(`A6:${last}6`).format.rowHeight=32;
 sheet.getRange(`A7:${last}${end}`).setNumberFormat('0.0000');
 sheet.getRange(`A1:C${end}`).format.columnWidth=16;
 sheet.freezePanes.freezeRows(6);
 if(name==='数字看板'){
  sheet.getRange('G7:G32').setNumberFormat('0');sheet.getRange('J7:J32').setNumberFormat('0.0000%');
  sheet.getRange('L1:L32').format.columnWidth=25;sheet.getRange('M1:M32').format.columnWidth=20;sheet.getRange('N1:N32').format.columnWidth=60;
  sheet.getRange('L7:L32').setNumberFormat('yyyy-mm-dd hh:mm:ss');
 }else if(name==='分位与样本'){
  sheet.getRange('E7:E80').setNumberFormat('0.00%');sheet.getRange('F7:H80').setNumberFormat('0');
  sheet.getRange('K1:L80').format.columnWidth=25;sheet.getRange('M1:M80').format.columnWidth=45;
  sheet.getRange('K7:L80').setNumberFormat('yyyy-mm-dd hh:mm:ss');
 }else if(name==='研究指标'){
  sheet.getRange('D1:D800').format.columnWidth=24;sheet.getRange('E1:E800').format.columnWidth=29;
  sheet.getRange('I1:I800').format.columnWidth=25;sheet.getRange('J1:K800').format.columnWidth=65;
  sheet.getRange('I7:I800').setNumberFormat('yyyy-mm-dd hh:mm:ss');
 }else if(name==='来源与状态'){
  sheet.getRange('A1:A32').format.columnWidth=25;sheet.getRange('B1:B32').format.columnWidth=110;
  sheet.getRange('A7:B32').setNumberFormat('@');
  sheet.getRange('B7:B32').format.wrapText=true;sheet.getRange('A7:B32').format.rowHeight=48;
 }
}
const {addViews}=await import('./view_template.mjs');
addViews(wb,metadata);
wb.recalculate();await fs.mkdir(path.dirname(destination),{recursive:true});
await(await SpreadsheetFile.exportXlsx(wb)).save(destination);
console.log(JSON.stringify({template:destination,sheets:wb.worksheets.items.length,containsBusinessData:false}));
// Optional synthetic preview data is loaded only AFTER exporting the blank template.
if(process.argv[4]){
 const sample=JSON.parse(await fs.readFile(process.argv[4],'utf8'));
 for(const [name,rows] of Object.entries(sample.sheets)){
  if(!rows.length)continue;
  const width=sample.headers[name].length;
  wb.worksheets.getItem(name).getRange(`A7:${String.fromCharCode(64+width)}${rows.length+6}`).values=rows;
 }
 if(sample.research){
  for(const [id,name] of [['basis','期现'],['calendar','同品种跨期'],['cross','跨品种']]){
   const s=wb.worksheets.getItem(name),p=sample.research.excel_pages[id];
   const selected=sample.research.pages[id]?.selection||{};
   for(const [cell,key] of [['B3','variant_id'],['E3','scope'],['H3','root'],['K3','left'],['N3','right'],['B4','timing'],['E4','date'],['H4','expiry_mode'],['K4','offset'],['N4','limit'],['B8','participation']]){
    if(selected[key]!==undefined)s.getRange(cell).values=[[selected[key]]];
   }
   if(p.directory.length)s.getRange(`A13:E${12+p.directory.length}`).values=p.directory;
   if(p.entities.length)s.getRange(`G13:Q${12+p.entities.length}`).values=p.entities;
   if(p.details.length){s.getRange(`A280:K${279+p.details.length}`).values=p.details;s.getRange(`A280:K${279+p.details.length}`).format.autofitRows();}
   s.getRange('A9').values=[[p.status]];
  }
 }
 wb.recalculate();
 for(const [name,range] of [['期现','A1:Q22'],['同品种跨期','A1:Q22'],['跨品种','A1:Q22'],['期现','A279:K284'],['来源与状态','A1:B16']]){
  const png=await wb.render({sheetName:name,range,scale:1.2,format:'png'});
  await fs.writeFile(path.join(path.dirname(process.argv[4]),name+(range.startsWith('A279')?'_详情':'')+'.png'),new Uint8Array(await png.arrayBuffer()));
 }
 console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!',options:{useRegex:true,maxResults:10},maxChars:1500})).ndjson);
}
