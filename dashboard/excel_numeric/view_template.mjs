// Presentation formulas only. numeric_view.py supplies existing engine values.
export function addViews(wb, metadata) {
 const ink='#203348', muted='#64748B', blue='#244C72', teal='#087E8B', pale='#F2F6FA', font='Microsoft YaHei';
 const overview=wb.worksheets.add('概览'), indicators=wb.worksheets.add('指标');
 const setup=(s,range)=>{s.showGridLines=false;const f=s.getRange(range).format;f.font={name:font,size:11,color:ink};f.rowHeight=19;f.columnWidth=9;f.verticalAlignment='center';};
 const block=(s,range,text,opts={})=>{const r=s.getRange(range);r.merge();r.values=[[text]];r.format.font={name:font,size:opts.size||11,color:opts.color||ink,bold:!!opts.bold};if(opts.fill)r.format.fill=opts.fill;return r;};
 const formula=(s,range,source,col,index,format='0.00')=>{
   const r=s.getRange(range);r.merge();
   const ref=`INDEX('${source}'!${col}$7:${col}$406,${index})`;
   r.formulas=[[`=IF(ISBLANK(${ref}),"",${ref})`]];r.setNumberFormat(format);r.format.horizontalAlignment='center';return r;
 };
 const selector=s=>{block(s,'B3:D3','档位');s.getRange('E3').values=[[0]];s.getRange('E3').setNumberFormat('00');s.getRange('E3').format.fill='#FFF0C2';s.getRange('E3').dataValidation={rule:{type:'list',values:['0','1','2','3']}};};
 setup(overview,'A1:S44');overview.tabColor=blue;
 for(const c of ['A','J','S'])overview.getRange(`${c}1:${c}44`).format.columnWidth=3;
 block(overview,'B2:R2','DELTA1  股指看板',{size:18,bold:true});overview.getRange('B2:R2').format.rowHeight=28;
 selector(overview);block(overview,'G3:R3','待连接',{color:muted});block(overview,'B4:R4','加载中',{color:muted});
 const cards=[];
 for(let p=0;p<4;p++){
   const start=p%2?11:2,r=p<2?6:19,letter=n=>String.fromCharCode(64+n),a=letter(start),z=letter(start+7),idx=`$E$3*4+${p+1}`;
   overview.getRange(`${a}${r}:${z}${r+11}`).format.fill=pale;
   block(overview,`${a}${r}:${letter(start+2)}${r}`,['IF','IH','IC','IM'][p],{size:17,bold:true,color:teal});
   formula(overview,`${letter(start+3)}${r}:${z}${r}`,'卡片数据','C',idx,'@');
   ['期货','指数','基差 bp','年化'].forEach((name,i)=>{
     const l=letter(start+i*2),h=letter(start+i*2+1);
     block(overview,`${l}${r+1}:${h}${r+1}`,name,{color:muted});
     formula(overview,`${l}${r+2}:${h}${r+2}`,'卡片数据',['D','E','F','G'][i],idx,i===3?'0.00%':'#,##0.00').format.font={name:font,size:16,bold:true,color:ink};
   });
   const metrics=[['收敛 bp/日','H','振幅 倍','I'],['路径效率','J','中枢 %','K'],['换手 倍','L','活跃度 倍','M']];
   for(let j=0;j<3;j++){
     const row=r+4+j,[l,c,l2,c2]=metrics[j];
     block(overview,`${a}${row}:${letter(start+1)}${row}`,l,{size:10,color:muted});
     formula(overview,`${letter(start+2)}${row}:${letter(start+3)}${row}`,'卡片数据',c,idx);
     block(overview,`${letter(start+4)}${row}:${letter(start+5)}${row}`,l2,{size:10,color:muted});
     formula(overview,`${letter(start+6)}${row}:${z}${row}`,'卡片数据',c2,idx);
   }
   ['20日','3月','6月','12月'].forEach((t,i)=>{
     const l=letter(start+i*2),h=letter(start+i*2+1);
     block(overview,`${l}${r+8}:${h}${r+8}`,t,{color:muted});
     formula(overview,`${l}${r+9}:${h}${r+9}`,'卡片数据',['N','O','P','Q'][i],idx,'0%');
     formula(overview,`${l}${r+10}:${h}${r+10}`,'卡片数据',['R','S','T','U'][i],idx,'"n="0');
   });
   // Each card keeps its own source time and historical cutoff; no global newest-time masking.
   const rr=overview.getRange(`${a}${r+3}:${z}${r+3}`);rr.merge();
   const ref=c=>`INDEX('卡片数据'!${c}$7:${c}$22,${idx})`;
   rr.formulas=[[`=IF(ISBLANK(${ref('W')}),"待计算",${ref('Y')}&" "&TEXT(${ref('W')},"mm/dd hh:mm:ss"))&IF(ISBLANK(${ref('X')}),""," · 历史 "&TEXT(${ref('X')},"mm/dd"))`]];
   rr.format.font={name:font,size:9,color:muted};rr.format.horizontalAlignment='center';
   const footer=formula(overview,`${a}${r+11}:${z}${r+11}`,'卡片数据','V',idx,'@');
   footer.format.font={name:font,size:9,color:muted};footer.format.wrapText=true;footer.format.rowHeight=30;
   cards.push(`${a}${r+9}`);
 }
 for(const r of [6,8,19,21])overview.getRange(`B${r}:R${r}`).format.rowHeight=25;
 block(overview,'B41:R41','未连接 · 保存文件为快照',{size:10,color:muted});
 block(overview,'B42:R42','计算 / 写入 / 保存：待完成',{size:10,color:muted});
 const helper=wb.worksheets.getItem('卡片数据');
 helper.getRange('Z6:AA6').values=[['品种','20日分位']];
 for(let p=0;p<4;p++){
   helper.getRange(`Z${p+7}`).values=[[['IF','IH','IC','IM'][p]]];
   // NA is deliberate in the hidden chart source: absent percentiles are not zero.
   helper.getRange(`AA${p+7}`).formulas=[[`=IF(ISNUMBER('概览'!${cards[p]}),'概览'!${cards[p]},NA())`]];
 }
 const chart=overview.charts.add('bar',helper.getRange('Z6:AA10'));chart.title='20日分位';chart.hasLegend=false;chart.series.items[0].fill=teal;
 chart.yAxis={numberFormatCode:'0%',numberFormatSourceLinked:false};chart.setPosition('B32','R39');
 setup(indicators,'A1:P39');indicators.tabColor=teal;indicators.getRange('A1:A39').format.columnWidth=3;
 indicators.getRange('B1:B39').format.columnWidth=18;indicators.getRange('C1:C39').format.columnWidth=10;
 for(const col of ['E','H','K','N'])indicators.getRange(`${col}1:${col}39`).format.columnWidth=17;
 for(const col of ['F','I','L','O'])indicators.getRange(`${col}1:${col}39`).format.columnWidth=15;
 block(indicators,'B2:O2','DELTA1  指标',{size:18,bold:true});indicators.getRange('B2:O2').format.rowHeight=28;selector(indicators);
 block(indicators,'G3:O3','年化输入 · %列按百分点显示',{color:muted});
 block(indicators,'B4:O4','加载中',{color:muted});
 const labels=['指标','单位',...['IF','IH','IC','IM'].flatMap(p=>[p,'数据时间','状态'])];
 indicators.getRange('B6:O6').values=[labels];indicators.getRange('B6:O6').format={fill:blue,font:{name:font,size:11,color:'#FFFFFF'},rowHeight:27};
 const count=metadata.metrics.length;
 metadata.metrics.forEach(([id,label,unit],i)=>{
   const r=7+i,idx=`$E$3*${count}+${i+1}`;
   indicators.getRange(`B${r}`).values=[[label]];formula(indicators,`C${r}`,'指标数据','D',idx,'@');
   for(let p=0;p<4;p++){
     for(let k=0;k<3;k++)formula(indicators,`${String.fromCharCode(68+p*3+k)}${r}`,'指标数据',String.fromCharCode(69+p*3+k),idx,k===0?'0.00':k===1?'mm/dd hh:mm':'@');
   }
   indicators.getRange(`B${r}:O${r}`).format.rowHeight=25;
   if(i%2===0)indicators.getRange(`B${r}:O${r}`).format.fill=pale;
 });
 indicators.freezePanes.freezeRows(6);
 block(indicators,'B34:O34','样本/分母：历史不足、输入缺失或分母无效；完整原因见研究指标。',{size:10,color:muted});
 block(indicators,'B35:O35','未连接 · 保存文件为快照',{size:10,color:muted});
 return {overview,indicators};
}
