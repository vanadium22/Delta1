// Developer-only template authoring. Company runtime needs Python + desktop Excel.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const {Workbook,SpreadsheetFile}=await import(process.env.ARTIFACT_TOOL_MODULE ? pathToFileURL(process.env.ARTIFACT_TOOL_MODULE).href : '@oai/artifact-tool');
const destination=process.argv[2];
if(!destination)throw new Error('Pass the output template.xlsx path');
const headers={
 '数字看板':['品种','档位','具体合约','期货 F','指数 S','分红 D 点','T 自然日','基差 点','基差 bp','年化 %','数据类型','数据时间（北京）','当前挂牌合约','说明'],
 '分位与样本':['品种','档位','具体合约','窗口','分位 %','有效 n','缺失日','排除日','定位值','单位','定位时间（北京）','参考截止（北京）','说明'],
 '研究指标':['品种','档位','具体合约','指标ID','指标名称','数值','单位','数据类型','数据时间（北京）','可用性说明','口径 / 公式'],
 '来源与状态':['项目','内容'],
};
const wb=Workbook.create();
for(const [name,cols] of Object.entries(headers)){
 const sheet=wb.worksheets.add(name);sheet.showGridLines=false;
 const last=String.fromCharCode(64+cols.length), end=name==='研究指标'?800:name==='分位与样本'?80:32;
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
 }else{
  sheet.getRange('A1:A32').format.columnWidth=25;sheet.getRange('B1:B32').format.columnWidth=110;
  sheet.getRange('A7:B32').setNumberFormat('@');
  sheet.getRange('B7:B32').format.wrapText=true;sheet.getRange('A7:B32').format.rowHeight=48;
 }
}
wb.recalculate();await fs.mkdir(path.dirname(destination),{recursive:true});
await(await SpreadsheetFile.exportXlsx(wb)).save(destination);
console.log(JSON.stringify({template:destination,sheets:4,containsBusinessData:false}));
