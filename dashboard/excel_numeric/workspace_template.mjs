// Layout only: labels and independent variant mappings come from Python.
export const RESEARCH_PAGES = [['basis','期现'],['calendar','同品种跨期'],['cross','跨品种']];
export const SCOPE_LABELS={representatives:'默认代表',all:'全部合约',history:'历史合约',specified:'指定合约'};
export const EXPIRY_LABELS={same:'相同到期',all:'全部期限',mixed:'不同到期'};
const font='Microsoft YaHei',ink='#203348',muted='#64748B',blue='#244C72',pale='#F2F6FA';
function text(s,cell,value){s.getRange(cell).values=[[value]];}
function merge(s,range,value){s.getRange(range).merge();text(s,range.split(':')[0],value);}
function input(s,range,value){if(range.includes(':'))s.getRange(range).merge();text(s,range.split(':')[0],value);s.getRange(range).format.fill='#FFF0C2';}
export const WORKSPACE_LINKS=[];
function link(s,range,target,label){if(range.includes(':'))s.getRange(range).merge();const cell=range.split(':')[0];text(s,cell,label);WORKSPACE_LINKS.push({sheet:s.name,cell,target,label});s.getRange(range).format.font={name:font,size:11,color:blue};}
function base(s,last='F',rows=42){s.showGridLines=false;const a=s.getRange(`A1:${last}${rows}`);a.format.font={name:font,size:11,color:ink};a.format.rowHeight=22;a.format.verticalAlignment='center';}
export function addWorkspace(wb,metadata={}) {
 const choices=wb.worksheets.add('合约选项');choices.showGridLines=false;
 const directory=wb.worksheets.add('指标目录');base(directory,'F',420);
 merge(directory,'A2:F2','全部指标与独立输入口径');directory.getRange('A2').format.font={name:font,size:16,bold:true,color:ink};
 merge(directory,'A4:F4','可用 Excel 筛选查找；返回研究页选择中文指标与输入。技术 ID 可粘贴到指标格，自动迁移。');
 link(directory,'A3:B3','期现','返回期现');link(directory,'C3:D3','同品种跨期','返回同品种跨期');link(directory,'E3:F3','跨品种','返回跨品种');
 directory.getRange('A6:F6').values=[['类别','指标','输入口径','指标族 ID','独立变体 ID','适用说明']];
 const catalog=metadata.catalog||[];let directoryRows=[];
 for(const [i,[id,name]] of RESEARCH_PAGES.entries()) {
  const controls=metadata.ui_controls?.[id]||{families:[],inputs:[],variants:[]};
  const applicable=catalog.filter(r=>(r.categories||[]).includes(id));
  const chosen=controls.variants.find(v=>v.family_id==='A03.percentile'&&v.input_id==='basis')||controls.variants[0]||{};
  const s=wb.worksheets.add(name);base(s);s.tabColor=i===0?blue:i===1?'#087E8B':'#536B82';
  for(const [col,width] of Object.entries({A:28,B:17,C:14,D:21,E:7,F:30}))s.getRange(`${col}1:${col}42`).format.columnWidth=width;
  merge(s,'A2:F2','DELTA1  '+name);s.getRange('A2').format.font={name:font,size:16,bold:true,color:ink};s.getRange('A2:F2').format.rowHeight=30;
  text(s,'A3','指标');input(s,'B3:C3',chosen.family_label||'');text(s,'D3','输入 X');input(s,'E3:F3',chosen.input_label||'分红调整基差（bp）');
  s.getRange('B3:C3').format.wrapText=true;s.getRange('E3:F3').format.wrapText=true;s.getRange('A3:F3').format.rowHeight=32;
  text(s,'A4','观察时点');input(s,'B4:C4','日终');text(s,'D4','观察范围');input(s,'E4:F4','默认代表');
  merge(s,'A5:F5','未连接。请使用原启动器打开维护中的工作簿。');
  merge(s,'A6:F6','等待当前指标结果');s.getRange('A6:F6').format.rowHeight=30;
  link(s,'A7:B7',name+'详情','展开详情 / 高级筛选');link(s,'C7:D7','指标目录','全部指标 / 更多口径');link(s,'E7:F7','概览','对应指数看板');
  s.getRange('A9:F9').values=[['代表 / 合约','数值','单位','源时（北京）','有效 n','数据状态']];
  s.getRange('A9:F9').format={fill:blue,font:{name:font,size:11,color:'#FFFFFF',bold:true},rowHeight:26};
  s.getRange('A10:F33').format.rowHeight=32;s.getRange('A10:A33').format.wrapText=true;s.getRange('F10:F33').format.wrapText=true;
  for(let r=10;r<=33;r+=2)s.getRange(`A${r}:F${r}`).format.fill=pale;
  s.getRange('B10:B33').setNumberFormat('0.0000');s.getRange('D10:D33').setNumberFormat('mm/dd hh:mm:ss');s.getRange('E10:E33').setNumberFormat('0');
  s.getRange('C9:C33').format.horizontalAlignment='center';s.getRange('C10:C33').format.wrapText=true;s.getRange('E9:E33').format.horizontalAlignment='center';
  s.freezePanes.freezeRows(9);
  merge(s,'A35:F35','黄色格可编辑。默认代表为 T−1 证据选择；源时与历史可见性详见详情。');
  merge(s,'A36:F36','更多口径请在输入 X 选“更多口径”，再到详情页选择具体原始 / 对数口径。');
  s.getRange('A35:F36').format.font={name:font,size:11,color:muted};
  s.getRange('B4').dataValidation={rule:{type:'list',values:['日终','盘中优先','历史日']}};
  s.getRange('E4').dataValidation={rule:{type:'list',values:Object.values(SCOPE_LABELS)}};
  const primary=controls.inputs.filter(x=>!x.advanced&&x.input_id!=='fixed');
  s.getRange('E3').dataValidation={rule:{type:'list',values:[...primary.map(x=>x.label),'更多口径','固定口径']}};
  const familyCol=String.fromCharCode(66+i),advancedCol=String.fromCharCode(69+i);
  if(controls.families.length){choices.getRange(`${familyCol}7:${familyCol}${6+controls.families.length}`).values=controls.families.map(x=>[x.label]);s.getRange('B3').dataValidation={rule:{type:'list',formula1:`'合约选项'!$${familyCol}$7:$${familyCol}$${6+controls.families.length}`}};}
  const d=wb.worksheets.add(name+'详情');base(d,'K',1800);d.tabColor='#94A3B8';
  for(const [col,width] of Object.entries({A:30,B:22,C:14,D:28,E:23,F:8,G:17,H:24,I:48,J:50,K:58}))d.getRange(`${col}1:${col}1800`).format.columnWidth=width;
  merge(d,'A2:F2',name+' · 详情与高级筛选');d.getRange('A2').format.font={name:font,size:16,bold:true,color:ink};link(d,'G2:H2',name,'返回研究结果');
  for(const [label,cell,value] of [['品种','B3',''],['合约 A','E3',''],['合约 B','H3',''],['历史日期','B4',''],['期限','E4',id==='cross'?'相同到期':'全部期限'],['起始序号','H4',0],['每页实体','B5',12],['参与比例 p','E5',null],['更多口径','B7','']]){const c=cell[0],r=cell.slice(1);text(d,String.fromCharCode(c.charCodeAt(0)-1)+r,label);input(d,cell,value);}
  d.getRange('B4').setNumberFormat('@');d.getRange('E5').setNumberFormat('0.00%');
  d.getRange('B7:C7').merge();d.getRange('B7:C7').format.fill='#FFF0C2';d.getRange('B7:C7').format.wrapText=true;
  merge(d,'A6:H6','p 只用于容量演算，空白不计算；合法 0 保留。指定腿、历史日期和分页仅在相应范围生效。');
  merge(d,'D7:H7',id==='cross'?'不同指数期货点位不直接相减，请选择适用的基差 / 年化口径。':'close 取日终收盘；盘中优先使用实际最新价，源时单列显示。');
  d.getRange('A7:H7').format.rowHeight=32;d.getRange('D7:H7').format.wrapText=true;
  merge(d,'A8:H8','当前选择 / 固定口径 / 完整缺失原因');
  d.getRange('B3').dataValidation={rule:{type:'list',values:['','IF','IH','IC','IM']}};d.getRange('E4').dataValidation={rule:{type:'list',values:Object.values(EXPIRY_LABELS)}};d.getRange('B5').dataValidation={rule:{type:'list',values:['4','6','12','24']}};
  const advanced=controls.inputs.filter(x=>x.advanced);if(advanced.length){text(d,'B7',advanced[0].label);choices.getRange(`${advancedCol}7:${advancedCol}${6+advanced.length}`).values=advanced.map(x=>[x.label]);d.getRange('B7').dataValidation={rule:{type:'list',formula1:`'合约选项'!$${advancedCol}$7:$${advancedCol}$${6+advanced.length}`}};}
  d.getRange('A10:K10').values=[['实体 / 指标','值','单位','各腿源时','历史截止','n','实现状态','数据状态','输入 / 公式版本','原因 / 代表依据','公式']];
  d.getRange('A10:K10').format={fill:blue,font:{name:font,size:11,color:'#FFFFFF',bold:true},rowHeight:28};
  d.getRange('A11:K1800').format.rowHeight=28;d.getRange('A11:K1800').format.verticalAlignment='top';d.getRange('A11:A1800').format.wrapText=true;d.getRange('D11:D1800').format.wrapText=true;d.getRange('G11:K1800').format.wrapText=true;d.getRange('B11:B1800').setNumberFormat('0.0000');d.getRange('E11:E1800').setNumberFormat('mm/dd hh:mm:ss');d.getRange('F11:F1800').setNumberFormat('0');d.freezePanes.freezeRows(10);
  for(const entry of applicable){const v=controls.variants.find(v=>v.variant_id===entry.variant_id)||{};directoryRows.push([name,v.family_label||entry.title,v.input_label||entry.input_id,entry.family_id,entry.variant_id,v.input_id==='fixed'?'固定经济定义，不受 X 影响':'独立输入变体']);}
 }
 if(directoryRows.length){directory.getRange(`A7:F${6+directoryRows.length}`).values=directoryRows;directory.tables.add(`A6:F${6+directoryRows.length}`,true,'IndicatorDirectory');}
 for(const [col,width] of Object.entries({A:17,B:32,C:35,D:23,E:48,F:32}))directory.getRange(`${col}1:${col}420`).format.columnWidth=width;
 directory.freezePanes.freezeRows(6);
 return choices;
}
