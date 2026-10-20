// Compact watchlist: editable legs above, classified intraday / daily results below.
export function addWorkspace(wb) {
 const s=wb.worksheets.add('组合对比'), choices=wb.worksheets.add('合约选项');
 s.showGridLines=false;s.tabColor='#087E8B';choices.showGridLines=false;
 const r=s.getRange('A1:P99');r.format.font={name:'Microsoft YaHei',size:10,color:'#203348'};
 r.format.columnWidth=12;r.format.rowHeight=24;r.format.verticalAlignment='center';
 s.getRange('A2:P2').merge();s.getRange('A2').values=[['DELTA1  关注组合']];s.getRange('A2').format.font={size:18,bold:true};
 s.getRange('A3').values=[['指标分类']];s.getRange('B3').values=[['全部']];
 s.getRange('D3').values=[['研究第几组']];s.getRange('E3').values=[[1]];
 s.getRange('B3').dataValidation={rule:{type:'list',values:['全部','定价与期限','位置与趋势','波动与形态','成交与活跃','持仓与结构','盘口与规模']}};
 s.getRange('E3').dataValidation={rule:{type:'list',values:['1','2','3','4','5','6','7','8']}};
 s.getRange('A4:P4').merge();s.getRange('A4').values=[['黄色格可选；期现B留空自动配指数。历史日期填YYYY-MM-DD。组合保存在本机。']];
 s.getRange('A4').format.font.color='#64748B';
 s.getRange('A5:P5').merge();s.getRange('A5').values=[['未连接 · 仅启动器维护的窗口可计算选择']];
 s.getRange('A5').format.font={name:'Microsoft YaHei',size:9,color:'#64748B'};
 s.getRange('A6:P6').values=[['类型','合约A','合约B / 指数','输入','时点','历史日期','输入值','单位','路径效率','Z','A腿日内换手','同刻活跃','振幅','盘中源时','日终日期','状态']];
 s.getRange('A7:F14').format.fill='#FFF0C2';s.getRange('B3').format.fill='#FFF0C2';s.getRange('E3').format.fill='#FFF0C2';
 s.getRange('F7:F14').setNumberFormat('@');
 for(const [col,values] of [['A',['期现','跨期','跨指数']],['D',['期货价','基差bp','年化']],['E',['盘中优先','日终','历史日']]]) {
  s.getRange(`${col}7:${col}14`).dataValidation={rule:{type:'list',values}};
 }
 s.getRange('G7:M14').setNumberFormat('0.00');s.getRange('N7:N14').setNumberFormat('mm/dd hh:mm:ss');s.getRange('O7:O14').setNumberFormat('mm/dd');
 s.getRange('B1:C99').format.columnWidth=18;s.getRange('F1:F99').format.columnWidth=16;
 s.getRange('N1:N99').format.columnWidth=20;s.getRange('P1:P99').format.columnWidth=25;
 s.getRange('A17:P17').merge();s.getRange('A17').values=[['选择上方组合，下面按分类列示盘中与日终结果']];s.getRange('A17').format.font.color='#087E8B';
 s.getRange('A19:I19').values=[['分类','指标','单位','盘中值','盘中源时','盘中口径','日终值','日终日期','说明']];
 s.getRange('D20:D99').setNumberFormat('0.00');s.getRange('G20:G99').setNumberFormat('0.00');
 s.getRange('E20:E99').setNumberFormat('mm/dd hh:mm:ss');s.getRange('H20:H99').setNumberFormat('mm/dd');
 s.getRange('E1:E99').format.columnWidth=20;
 s.getRange('B20:B99').format.wrapText=true;s.getRange('A20:I99').format.rowHeight=38;
 s.getRange('I20:P99').format.wrapText=false;
 for(const row of ['A6:P6','A19:I19'])s.getRange(row).format={fill:'#244C72',font:{name:'Microsoft YaHei',size:10,color:'#FFFFFF',bold:true},rowHeight:28};
 for(let row=20;row<100;row+=2)s.getRange(`A${row}:I${row}`).format.fill='#F2F6FA';
 s.freezePanes.freezeRows(6);
 choices.getRange('A6').values=[['具体合约与指数']];
 return s;
}
