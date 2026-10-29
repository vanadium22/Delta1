# 公司数据能力与行情分析验收

2026-10-29。本次公司同日NAV/未复权close配对12/12、Nav阶段和收盘折溢价截图已确认；IOPV/份额/PCF仍缺核验定义。入口均已实现，默认Runtime复测和可选Full命令以APP_COMPANY_TEST为准。默认 `-Overview` 仍离线；新ETF测试必须显式 `-Stage ETF` 才调用Wind，没有正式资料发布、订阅、VPN切换或配置改写。测试返回非空不等于字段业务含义、时点和单位已全部核验。

## 更新和分红

公司更新、确认Y源、Local/Share/Import、可选InputFile以及完整回传命令统一在 [APP_COMPANY_TEST](../APP_COMPANY_TEST.md)。源为 `Y:\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026`，Y:映射192.168.91.230，本次公司实录DisplayRoot为 `\\192.168.91.230\FTPServer`，默认仍用Y，不猜拼或重新映射。年份目录、Sheet1!B1业务日、原配置/源文件保护和历史D缺项判断均按当前公司步骤执行。

## 指数行业

```powershell
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -WindStage Indices -NoPause
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -WindStage ETFs -NoPause
```

只读阶段成功不会发布。正常打开看板后，后台完整资料至少周度复核；名单/行业/权重过旧或缺项、ETF排名不完整时，每个完成交易日每天最多一次修复，跨重启去重；另有每日NAV任务。显式刷新可重测，持续失败不会每三秒重连。正常任务发布后，下一次60秒成分快照使用相同资料版本；部分权重不补零、不重归一化，未知字段不冒充已抓到。

指数页下方、页面数据 `index_details.<品种>.inputs` 及Overview每次样本的 `indices.<品种>.inputs` 分别列出缺权重、缺行业、无效报价/昨收数量、快照版本是否匹配和指数昨收是否有效。行业“篮子涨跌”必须全行业成分行情和权重完整；“贡献点数”另需准确昨日权重和指数昨收。部分行业不显示完整贡献或参与排名，悬浮可见缺项。`expected=0`表示缺名单且股票缺口未知。

## ETF四项能力

```powershell
./dashboard/diagnose_data_capabilities.cmd -LocalRoot $deltaLocalRoot -Stage Local -NoPause
./dashboard/diagnose_data_capabilities.cmd -LocalRoot $deltaLocalRoot -Stage ETF -NoPause
```

Local仅盘点，不导入WindPy/不触网。ETF总预算90秒、最多12只ETF；优先已发布四指数规模前三，尚无排名时测试四只明确代表ETF。只查询同日单位NAV和未复权close，分别报告 `checks.close_nav/iopv/net_creation/pcf`。安全诊断保留失败阶段、ErrorCode、连接前后、日期、字段、返回形状及有效样本数；不导出原始驱动异常、凭据或原始返回值。不会把一项成功写成四项全可用。

默认没有经核验IOPV、份额或PCF定义，所以后三项返回 `mapping_required`；这不是接口失败证据。输出默认在 `dashboard/runtime/data_capabilities/<时间>/capabilities.json`。退出2表示测试失败或仍有未核验条件，应查看JSON；无需删缓存或重录凭据。现有收盘溢价依赖正常低频任务真正发布同日NAV/close，不能替代盘中IOPV。

若公司Wind代码生成器或正式数据说明能给出字段，把 [etf_fields.example.json](etf_fields.example.json) 复制到LocalRoot本地填写，再显式测试：

```powershell
./dashboard/diagnose_data_capabilities.cmd -LocalRoot $deltaLocalRoot -Stage ETF -FieldsFile (Join-Path $deltaLocalRoot 'etf_fields.json') -NoPause
```

字段文件是JSON元数据，不执行文本指令。每个非空分组必须有 `definition_source`（经核验的说明来源）；不把示例占位名称当真实Wind字段：

| 分组 | 必填元数据 | 实际请求与结果边界 |
|---|---|---|
| iopv | field、definition_source | 一次WSQ快照，不传回调，不订阅；核对证券和字段，只报告非空数。未核验源时间，故不计算实时折溢价 |
| shares | field、units、definition_source；可选options | WSD按准确上一完成日及完成日各取一次、Fill=Blank。units只允许shares/ten_thousand_shares/unknown；未核验拆分及份额定义前不输出净申赎金额 |
| pcf | dataset、fields数组、date_field、code_field、definition_source；可选options | WSET逐只测试；options中的{day}/{code}仅作字面参数替换。核对每行日期与证券，只报告覆盖和非空数；不猜状态编码 |

不要提交真实本地字段文件。IOPV不能猜reference或ETF代码+1；净申赎不能用成交量/规模变化代替；PCF须正式带日数据，页面能打开不算抓取完成。字段有返回也须回传结果并核验时间、单位、拆分及状态语义后，才可据此增加正式生产接入。

## 行情分析

正常看板同级页为：概览、指数、ETF、股指期货、行情分析、数据更新/设置。行情分析默认今日，填写完整标的代码、日期时刻、频率和字段，再点“查询并计算”；切页和重绘不启动查询。

股票/ETF/指数按需复用原SecurityService，沿用WindPy解释器及用户site；分离自有缓存/锁在 `LocalRoot/analysis_data`，已有独立App查询缓存仅复制相关哈希验证文件，不改原目录。完整已定稿窗口再次查询零请求；今日窗口每次手动查询刷新截至当前已完成周期，未来周期、午休不造分钟。原32项研究和报告服务不创建，不恢复全库分钟历史下载。

TWAP为有效等间隔分钟收盘均值近似；VWAP仅股票/ETF，成交量额必须成对有效且量>0，先按真实源说明确认单位。改单位会在已有结果上重算，无需再次联网。指数不提供点位VWAP；股指期货仅本看板已发布具体合约/逐日连续档位日线，期货分钟、快照和VWAP继续不冒称支持。

查询中输入锁定避免旧结果串到新标的；取消和关闭可终止自有只读SDK进程，缓存写入线程正常排空。导出CSV/统计/来源清单到 `LocalRoot/analysis_exports`，表格仅显示前500行，导出包含完整所选窗口。错误只保留阶段、类型和数字ErrorCode。`--no-realtime`、只读实例、离屏捕获禁止该页联网；冻结快照不创建新查询页。

## 公司回传

按 [APP_COMPANY_TEST](../APP_COMPANY_TEST.md) 顺序进行只读阶段、正常任务发布、开窗10–15分钟、Nav/离线Overview及白名单JSON ZIP；回传return_manifest、同次HEAD/映射、分红、ETF能力与各诊断JSON，并注明取样时窗口/页面和关闭耗时。不要将本页局部能力示例当完整验收流程。

本机无Y映射；此前旧源WinError53和本机WindPy导入失败只属开发机证据，不推断公司也如此。公司此前报告已确认WindPy存在。本地假SDK/构造页面或只读阶段成功均不等于公司正式发布和持续页面验收。IOPV/份额/PCF定义未核验时继续明确缺项。
