// Three views consume the shared Python registry. No business formula here.
export const RESEARCH_PAGES = [['basis','期现'],['calendar','同品种跨期'],['cross','跨品种']];
export function addWorkspace(wb, metadata={}) {
 const choices=wb.worksheets.add('合约选项');choices.showGridLines=false;
 choices.getRange('A6:D6').values=[['具体合约与指数','期现变体','跨期变体','跨品种变体']];
 const catalog=metadata.catalog||[];
 const font='Microsoft YaHei', ink='#203348', muted='#64748B', blue='#244C72', pale='#F2F6FA';
 for(const [i,[id,name]] of RESEARCH_PAGES.entries()) {
  const s=wb.worksheets.add(name);s.showGridLines=false;s.tabColor=i===0?blue:i===1?'#087E8B':'#536B82';
  const area=s.getRange('A1:Q620');area.format.font={name:font,size:10,color:ink};area.format.columnWidth=15;area.format.rowHeight=24;area.format.verticalAlignment='center';
  s.getRange('B1:B620').format.columnWidth=42;s.getRange('C1:C620').format.columnWidth=38;
  s.getRange('G1:G620').format.columnWidth=28;s.getRange('P1:Q620').format.columnWidth=40;
  s.getRange('A2:Q2').merge();s.getRange('A2').values=[['DELTA1  '+name]];s.getRange('A2').format.font={name:font,size:17,bold:true,color:ink};
  const applicable=catalog.filter(r=>(r.categories||[]).includes(id));
  const selected=applicable[0]?.variant_id||'';
  for(const [label,cell,value] of [['指标变体','B3',selected],['范围','E3','representatives'],['品种','H3',''],['合约A','K3',''],['合约B','N3',''],['时点','B4','盘中优先'],['历史日期','E4',''],['期限','H4','same'],['起始序号','K4',0],['每页实体','N4',12]]) {
   const col=cell[0],row=cell.substring(1);s.getRange(String.fromCharCode(col.charCodeAt(0)-1)+row).values=[[label]];
   s.getRange(cell).values=[[value]];s.getRange(cell).format.fill='#FFF0C2';
  }
  s.getRange('E4').setNumberFormat('@');
  s.getRange('A8').values=[['参与比例 p']];s.getRange('B8').format.fill='#FFF0C2';s.getRange('B8').setNumberFormat('0.00%');
  s.getRange('C8:Q8').merge();s.getRange('C8').values=[['仅B12容量演算使用，填0到1的小数；空白不计算，不默认参与比例。']];
  s.getRange('C8').format.font={name:font,size:10,color:muted};
  for(const [cell,values] of [['E3',['representatives','all','history','specified']],['H3',['','IF','IH','IC','IM']],['B4',['盘中优先','日终','历史日']],['H4',['same','all','mixed']],['N4',['4','6','12','24']]])s.getRange(cell).dataValidation={rule:{type:'list',values}};
  if(applicable.length){
   const col=String.fromCharCode(66+i);choices.getRange(`${col}7:${col}${6+applicable.length}`).values=applicable.map(r=>[r.variant_id]);
   s.getRange('B3').dataValidation={rule:{type:'list',formula1:`'合约选项'!$${col}$7:$${col}$${6+applicable.length}`}};
  }
  for(const row of [5,6,7,9,10])s.getRange(`A${row}:Q${row}`).merge();
  s.getRange('A5').values=[['未连接。仅由启动器维护的窗口会重算选择。']];
  s.getRange('A6').values=[['默认代表使用T−1完整OI/成交量证据。未认证历史可见性明确标示，00—03不表示主力。']];
  s.getRange('A7').values=[['全部/历史/指定范围按每页实体数分页；黄色格可编辑，变体目录可检索。']];
  s.getRange('A9').values=[['等待计算']];s.getRange('A10').values=[['下方目录每个变体独立保留。选择变体后加载代表或筛选实体，子输出在第280行起。']];
  s.getRange('A5:Q10').format.font={name:font,size:10,color:muted};
  s.getRange('A12:E12').values=[['指标族','独立变体ID','指标 / 输入','默认实体数','状态']];
  s.getRange('G12:Q12').values=[['实体','值','单位','源时','历史截止','n','实现状态','数据状态','原因','代表依据','可见性']];
  s.getRange('A279:K279').values=[['实体 / 指标','值','单位','源时','历史截止','n','实现状态','数据状态','输入及公式版本','原因','公式']];
  for(const range of ['A12:E12','G12:Q12','A279:K279'])s.getRange(range).format={fill:blue,font:{name:font,size:10,color:'#FFFFFF',bold:true},rowHeight:30,wrapText:true};
  if(applicable.length)s.getRange(`A13:E${12+applicable.length}`).values=applicable.map(r=>[r.family_id,r.variant_id,r.title,id==='cross'?6:4,'选择后计算']);
  for(let r=13;r<270;r+=2){s.getRange(`A${r}:E${r}`).format.fill=pale;s.getRange(`G${r}:Q${r}`).format.fill=pale;}
  s.getRange('H13:H266').setNumberFormat('0.0000');s.getRange('J13:K266').setNumberFormat('mm/dd hh:mm:ss');s.getRange('L13:L266').setNumberFormat('0');
  s.getRange('B280:B620').setNumberFormat('0.0000');s.getRange('D280:E620').setNumberFormat('mm/dd hh:mm:ss');
  s.getRange('F280:F1800').setNumberFormat('0');s.getRange('G13:G266').format.wrapText=true;
  s.getRange('G13:Q36').format.rowHeight=56;
  s.getRange('M13:Q266').format.wrapText=true;
  s.getRange('A280:K1800').format.font={name:font,size:10,color:ink};
  s.getRange('A280:K1800').format.rowHeight=28;
  s.getRange('A280:K1800').format.verticalAlignment='top';
  s.getRange('A280:A1800').format.wrapText=true;s.getRange('D280:D1800').format.wrapText=true;
  s.getRange('G280:K1800').format.wrapText=true;
  s.freezePanes.freezeRows(12);
 }
 return choices;
}
