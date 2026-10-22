# 盘中指标与关注组合（2026-10-20）

2026-10-22 界面简化后，输入X与指标族分开选择并真实联动到对应变体；固定口径明确标识。首屏保留代表结果，完整目录、详情及高级筛选通过展开/导航进入。原概览和对应指数保留。最新操作见 [UI_SIMPLIFICATION.md](UI_SIMPLIFICATION.md)，下方旧“组合对比”布局不再是当前入口。

2026-10-22 后续：本文盘中公式及守卫继续保留；“关注组合”独立入口已迁入期现、同品种跨期、跨品种三研究页。完整目录、独立X/原稿口径、代表选择/分页和结果契约见 [INDICATOR_IMPLEMENTATION.md](INDICATOR_IMPLEMENTATION.md)。旧research_watchlist.json不删除、不重写，兼容迁移到新独立偏好。原概览及对应指数保留，00—03仍是到期档位。下方八行组合页面和25项界面为历史实现记录。

历史补齐到T−1本身是正常的。此次把新鲜行情接入部分原先只有完整历史值的指标，同时保留原日终值、历史序列和分位口径。下载、计算、保存时间都不是行情源时间。

## 计算边界

| 指标 | 新增盘中结果 | 条件与限制 |
| --- | --- | --- |
| X 输入值/差 | 最新期货价、调整基差或年化；双腿A−B | 源时和接收时的腿间差≤3秒；基差/年化需对应指数、分红和到期日 |
| A03 Z/分位/五期变化 | 当前观测相对已完成历史 | Z/分位需连续20个先前交易日，五期变化需此前5日；缺日不缩短窗口，不拼接其他合约 |
| B10 路径效率 | 前5日与当前观测组成5段路径 | 保留原日终值；分母为0留空，合法结果0保留 |
| B04.Q.intraday | A腿当前累计成交量/昨日有效OI | 与原B04.Q全日换手分开；HTTP的0 OI不当作可靠持仓 |
| B04.doi/K | 有效实时OI对应的净变化/占比 | 缺OI或净变化绝对值大于累计成交量时留空 |
| B09.same_time | 累计量/此前20日同分钟累计量中位；双腿取ln比 | 20日截至该分钟必须完整；使用分钟末前0—3秒的同步观测，标“盘中分钟近似”，不插值 |
| B11期货价输入 | 当日已发生高低价、昨收形成的临时振幅压力 | 需前20日完整TR基准，不代表最终日振幅 |
| B11.sample基差/年化输入 | 同步采集段极差/前20日完整振幅中位 | 标“采集区间”和起点；断流>30秒或换采集运行号重置。不是全天OHLC，不从两腿日线高低价相减 |

A11/A12等完整分钟指标、收盘位置、部分持仓结构、成本带和ETF/IOPV不会凭一个最新价被补齐。缺分钟、OI、分红、成本/ETF输入仍留空。新上市合约没有的上市前样本不补造。盘中值不写回历史数据集，不进入已完成历史分位池。

仍只在已核验交易日北京时间09:29（含）至15:01（不含）接入新行情；午间报价另受连续会话守卫。原概览的保存行情回看保留真实时间，不保证是最终收盘。组合页无有效实时X时明确显示“日终参考”，不把日终值放入盘中列。

## 选择与展示

Excel新增“组合对比”，两版本地App新增“组合与分类”，共用研究引擎和`research_workspace.py`。

- 最多8组；类型、具体合约A、B/指数、输入、时点分别选择，清空A停用该行。
- 期现B留空自动匹配IF/沪深300、IH/上证50、IC/中证500、IM/中证1000，禁止错配指数。跨期要求同品种、近月在前。跨指数允许具体合约和不同月份，异月份明确标记；不同指数原始点位不直接相减，仅开放基差bp/年化。
- “期货价”盘中取最新价，日终/历史日取收盘价。输入选择影响适用的价格序列指标；固定基差定义、成交/OI仍按各自公式及单位计算。
- “盘中优先”对比行有有效实时X时只列盘中结果，缺项留空；无有效X时显示日终参考。下方明细始终分列盘中与日终。“历史日”填`YYYY-MM-DD`，读取该日15:01可见的历史，日期需早于今天。
- 六类：定价与期限、位置与趋势、波动与形态、成交与活跃、持仓与结构、盘口与规模。选择分类及第几组查看该组合的明细、单位、实际时点、盘中有效n和缺失原因。
- Excel黄色格修改后自动请求；App编辑后点“应用选择”。更改时清空旧结果，只有对应请求的结果可回填，避免旧组合数值挂在新名称下。刷新保持选择和滚动。
- 选择独立保存到当前配置目录的`research_watchlist.json`，不修改native.json、VPN或DDB配置。两端格式相同；独立配置目录不会自动覆盖彼此的选择。
- 关闭启动器后是静态快照，修改保存文件的选择不会计算；一次性导出也不持续维护。需要动态结果时使用原启动入口。

## 版本与来源

| 项目 | 路径、版本与入口 | 配置/数据、发布与更新 |
| --- | --- | --- |
| 统一数字Excel | `P:\project\swhy\Delta1\company-apps-worktree`；`codex/company-apps`；基于302014b；`dashboard\start_numeric_excel.cmd` | 独立`dashboard\localsetting\numeric_excel\native.json`所指历史、实时、参考和分红；本次按白名单发布，普通pull更新 |
| 旧展示/开发App | `P:\project\swhy\Delta1\project`；旧分支`codex/dashboard-history-release-20261019`、a070339及原有未提交内容；`start_presentation.cmd`/`start_development.cmd` | 原`dashboard\localsetting\native.json`和数据；本次前端及Qt测试只留本地、不推送，不切分支 |
| 共用后台 | 两目录`native/nonregression.py`、`native/card_data.py`、新增`native/intraday.py`、`research_workspace.py` | 四文件同步核验；其他旧后台未整体覆盖，数字启动/VPN/缓存范围实现仍以统一目录为准 |
| 公司安装 | `D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard`就是Git根目录；原swhy_delta1环境 | 最后明确SHA输出是60e5446；之后用户确认VPN流程测试通过，但未附新HEAD。本次是否更新以公司git log确认，不能从远端推断 |
| 旧离线代码包 | 统一目录`dashboard\runtime\distribution\company-apps-numeric-refresh-20261020.bundle`，旧60e5446 | 本次未重建，不含新增组合页及盘中扩展；在线优先pull |
| 独立数据包 | 同目录`dashboard-data-short-v2-20261019.zip`，原核验历史截至10/16 | 私有、未改、不进Git。普通更新不重导，不解压覆盖整个data |

旧文档中“四表无图”“合约对只能去App”“后台全未同步”等为历史版本，本次范围以本文为准。

## 验证范围

合成计算覆盖行情变化/时间错位、缺昨日/整日缺口、合法0/无效OI、同刻分钟分母、采集段重连、具体跨期差、历史选择、盘中缺项不回填。实际Excel以同一HWND/文件验证选择往返、源时间和单元格变化、相同缓存、日终切换及阅读位置。两版App在启动器原有本机swhy_delta1环境完成Qt交互验证。

本机保存数据只读性能抽查：四档首次约51.4秒、热循环约1.5秒；默认四组额外约1.2秒。首次先打开加载窗口。不是公司实时吞吐测试。证据位于忽略目录`.deps/numeric_realtime/`；当前公司逐指标的新行情、补齐范围、最新HEAD及长期运行仍需现场验收。

## 公司更新与检查

关闭本次数值Excel和启动器，保留其他Excel，在公司PowerShell执行：

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
git status --short
if ((git branch --show-current).Trim() -ne 'codex/company-apps') { throw '先核对分支，勿强制切换' }
git pull --ff-only origin codex/company-apps
if ($LASTEXITCODE -ne 0) { throw '更新未成功；保留修改，不要强制覆盖' }
git log -1 --oneline
$env:SWHY_DELTA1_PYTHON = 'D:\conda\envs\swhy_delta1\python.exe'
.\dashboard\start_numeric_excel.cmd
```

沿用已有历史/VPN向导；补齐T−1后等进程退出，按提示手工切回行情VPN，再验证并打开。无需重装、重配VPN或重导数据。实时测试勿加`-ReadOnlyCache`；时段外本就不应接入新行情。

在组合页选有足够历史的合约和“盘中优先”，检查当前交易会话的源时，以及B10、B04.Q.intraday、B09.same_time、B11/B11.sample盘中列及说明。改“日终”时盘中列清空，日终日期保持真实。换合约/输入时旧值先清空再回填；保持选中和滚动观察新行情。相同缓存不会仅因检查时间变化成为新行情。

如需只读诊断，在上述仓库目录执行：

```powershell
& $env:SWHY_DELTA1_PYTHON -B -X utf8 -m dashboard.numeric_diagnose --samples 2 --interval 10
```

诊断核对运行身份、后台、源时和原概览单元格；组合页另看黄色选择、盘中源时和日终列。本机合成通过与公司实机验收分别记录。
