# Delta1 国内指数与股指期货桌面看板

**当前入口：`start.cmd` / 桌面「Delta1 股指看板」**。默认启动实时采集和独立历史维护。
旧 `start_app`、Developer、Viewer 及网页启动入口已退役；下文历史版本说明仅作参考。
公司部署、保护 Wind 的数据包安装、单独分支的 Git 抓取/推送方法见 [DEPLOYMENT.md](DEPLOYMENT.md)。

**2026-10-19 启动自动维护（本次新增）**：研究看板启动后在独立低优先级进程中检查
`native.json.history_roots` 的真实日线、分钟缺口。只通过**已有网络路由**连接 DDB，
不调用 VPN 登录、选线路、切换或退出；DDB 不可达则等待并按 5 / 15 / 30 分钟退避重试。
实时 HTTP 采集器的连接、停止按钮和文件写入完全独立。源库滞后逐个任务冷却并轮转，
不会让一个长期缺口阻塞全部后续下载；凭据失败等待手动修正，避免重复登录锁号。

新「数据维护」页面显示目标交易日、代码/频率/日缺口、缺失条数、连续完整日期、最近发布、
下次重试、实际数据目录及发布版本，并提供立即重试、暂停历史任务、设置本机历史账号。
关闭看板会停止其拥有的历史子进程；没有安装 Windows 常驻服务或定时任务。
首轮核验所有本地分片较慢，后续按分片哈希、大小和修改时间缓存核验结果。

下载上限恒为上海时区**上一交易日**，即使当天已经收盘也不下载当天。
使用独立交易所休市日历（已核对 2025、2026 年），未来年度从上交所 HTTPS 公告刷新；
日历不完整则等待，不能用源库已有价格日期推断休市。默认维护起点为本地最早日线，
也可在 `native.json.history_start` 指定 YYYY-MM-DD。只补挂牌至到期区间内的具体合约，
例如 2026-10-19 新上市的 2706 不计入截至 10-16 的缺口。

下载保存在实际历史目录旁 `_maintenance/<目录组合标识>/downloads`，经过哈希、单位、
具体代码、挂牌区间、OHLC、最终状态和分钟会话时间点校验，按缺失键追加到同一个历史目录。
分钟完整性检查 09:31—11:30、13:01—15:00 的 240 个唯一结束时间点，不能用重复行凑数。
价格冲突保留原记录并标记待核验，不静默覆盖。发布前回读暂存分片校验；指数和期货的
不可变版本由 `publication.json` 一次切换，看板刷新始终读取同一批已发布版本。
`current.json` 是兼容指针；请通过维护入口更新这些已登记目录，外部写入造成分歧时任务会停止并提示核验。
未发布的暂存文件不被看板读取，崩溃后可重新补缺；原版本和来源证据保留。

完整操作、公司电脑配置和外部定时入口见 [历史维护说明](HISTORY_MAINTENANCE.md)。

**2026-10-19 一次性历史补库与分位诊断**：Z 盘仅作为本次离线导入来源，
看板启动、刷新和采集均不读取 Z 盘；Z 导入命令仍只供一次性手动使用。
手动复用入口为 `python -B -s -X utf8 -m dashboard.marketdata.history_backfill --force`，
它按原始数据当日 `month_contract_code` 将连续档位还原为具体合约，只补缺少的时间点。
源文件只读；输出、来源摘录、哈希、保留原值的冲突记录及剩余缺口均在
`data/market/index_futures/dashboard/history_backfill/`。
合并数据在 `normalized/backfilled_cn_index` 和 `normalized/backfilled_cn_index_future`，
配置切换到本地合并目录，原 `normalized/cn_index*` 数据保留。
该命令也会有限次尝试历史库原生数据查询，端口不可达就记录缺口，不调用 VPN 登录/切换。

首页的基差及年化分位均用 00—03 各自的连续档位历史，历史 T 使用当日具体合约到期日，
固定 D 仍取当前具体合约对应的分红情景。新 2706 缺分红时沿用同品种前一合约 2703，
真实分红补入后自动替换。分位排除定位当日，年化另排除 T<5；
窗口起点已覆盖但部分交易日缺失时，用有效样本计算并标明「缺 N 日」，悬停查看日期；
不足两日或窗口起点未覆盖不显示。零方差允许计算分位（相等值中位秩 50%），不再误当成无法计算。

当前数据维护链路：

| 数据 | 看板实际读取 | 更新方式与现有缺口 |
| --- | --- | --- |
| 实时报价 | `data/market/index_futures/dashboard/realtime` | 「开始实时」后公司 HTTP 每 2 秒采集；关闭看板后停止。轮询快照不自动转成完整分钟/日线。 |
| 日线、分钟历史 | `localsetting/native.json` 的 `history_roots`，现为本地合并目录 | 本地版本化 Parquet；启动和运行期间自动检查、通过 DDB 补到上一交易日，校验后整体发布。网络或源库未齐时等待重试。 |
| 合约及连续映射 | `localsetting/contract_reference/current.json` | 自动读取中金所交易参数并交叉验证实时具体代码；保留历史挂牌/到期参考。 |
| 分红 | `data/dividends/index_futures/inputs` 的有效 Excel 缓存值 | 每次计算选择表内日期最新的有效快照；需要外部提供并替换源表，没有自动生成分红预测的服务。 |

公司电脑使用上面的启动维护流程，也可用 `maintain_history.cmd` 在已有 DDB 网络时单独运行，
无需启动看板；与看板共享目录锁和缺口记录，不重复并发下载。
入库目标须与 `native.json.history_roots` 一致；本次切换到合并目录后，若只更新旧的
`normalized/cn_index*`，看板不会自动读取旧目录的新版本。后续维护应统一发布入口和有效目录。
还需要明确分红源表的负责人、交付日期与异常通知，以及历史更正的审核/版本保留和磁盘保留策略。
迁移电脑时需同时复制本地数据和合约参考，并调整配置中的绝对路径；加密凭据在公司电脑重新录入。

**2026-10-19 自动换月**：研究界面启动、运行跨日和开始采集时自动查询中金所交易参数，
按官方上市日/最后交易日重建 IF/IH/IC/IM 的 00—03 档，并用公司 HTTP 行情核对具体代码与有效价格。
成功后当日缓存；查询失败或部分行情缺失每 5 分钟重试，也可点「更新合约」立即重试。
「开始实时」使用动态档位订阅，跨日无需重启；单品种资料缺失会提示，不再阻断其他品种及指数。
打开界面自动检查合约参考和历史缺口，持续行情采集仍由「开始实时」启动。
需要启动后立即采集时运行 `python -B -s -X utf8 -m dashboard.native --start-realtime`。

原始官方 XML、不可变参考版本、查询/行情核验状态和首次迁移前配置保存在
`localsetting/contract_reference/`；原有历史参考保留，不猜挂牌日，不切换 VPN。
已登记参考路径更新为该目录的 `current.json`，界面与采集器共用原子更新的文件。
实时行情核验失败不会删除官方有效合约，也不会把旧合约继续作为到期后的订阅。

固定分红默认使用 Sheet1 的 **C 列具体合约 → G 列缓存分红**，到期日取独立合约参考，
不按旧档位标签滚动搬移数值。分红表缺少新合约时，沿用同品种前一到期合约的分红，
例如 `IF2706 ← IF2703`；界面明确显示「沿用/估计」。新表出现具体合约的实际值后自动优先使用，
包括实际零值。旧的固定情景文件保留；`dividend_missing_policy=previous_contract` 启用这一规则。
逐日分红模式仍按精确日期/合约读取。历史行情缺口不会用前一合约价格填充。

有限轮真实验证（会查询官方参数/公司行情并保存记录）：
```powershell
python -B -s -X utf8 -m dashboard.verify_realtime_connection --polls 3 --refresh-contracts
```
本次 2706 换月集成验收：`python -B -s -X utf8 -m dashboard.validate_rollover`。
离线回归：`python -B -s -m unittest tests.test_dashboard_rollover tests.test_dashboard_continuous -v`。

**2026-10-16 当前默认界面**：沿用 PySide6 / pyqtgraph。首页为四品种大数字与连续档位分位图，
00—03 通过逐日挂牌/到期参考映射，同时显示 `IF03 · IF2703` 等具体身份。
固定分红快照情景与真实逐日分红明确区分；第二部分仍按具体合约研究，点进卡片可切换多品种图表、详细公式解释和数据状态。
字体、导航和下拉入口已放大。配置指向外层 `project/data`；界面读取本地已发布数据，
历史维护在独立进程运行，实时采集需手动开始。
双击 `dashboard/start_app.cmd` 启动；见 [本次连续档位及可读性改造](native/CONTINUOUS_CARDS_20261016.md)。
以下早期页面、回归和发布功能说明保留作兼容记录，不代表当前默认研究界面。

2026-10-02：PySide6 原生 Windows App，石墨金主题，pyqtgraph 交互图表。
市场层包含四股指期货概览、专题与自定义指标、市场异动三个页面。
开发工作台另有公式、数据与任务、结果档案。对外生成 **Delta1 市场看板** 的独立 Git。
2026-10-12：本机已通过项目公共 DDB 接口接入真实股指日线、分钟数据和16个具体合约的挂牌/到期资料。
「专题与自定义指标」新增一多一空研究：16项期现、24组跨期、24组同月跨指数组合，含方向解释、历史图、收益分解和对冲手数。
详细数据范围、公式与复现命令见 [一多一空基差研究](native/BASIS_RESEARCH.md)。新机器仍需显式注册本机数据路径；ETF 保留待接入状态。

2026-10-13：已在本机实时行情内网验证现有 HTTP 接口，16 个具体股指合约和 4 个指数全部返回。
本机实时目录为 `data/realtime_market`，已保存至 `localsetting/native.json`；历史目录继续使用上述 DDB 下载数据。
重新打开开发者版，在「数据与任务」点击「开始采集」即可每 2 秒轮询；打开应用本身不会自动开始采集。
本次仅作有限轮验证，未留下后台持续采集进程。连接记录见 `data/realtime_market/verification/latest.json`。
指数卡片和盘口读取实时观测；历史 K 线及基差 Z / β 仍取已注册的历史数据。接口只提供时分秒，缺少完整行情日期，盘后缓存报价不能视为新成交或标准分钟线。

可复用的有限轮验证命令（不调用 DDB，不切换 VPN）：

```powershell
python -B -X utf8 -s -m dashboard.verify_realtime_connection --polls 3 --register
```

命令复用原有采集器和存储模块，保存原始响应、SQLite、Parquet 及验证报告；成功后注册目录并发布看板快照。

## 启动

- `dashboard/start_developer.cmd`：六页面工作台；原 `start_app.cmd`、`start_dashboard.cmd` 默认同一入口。
- `dashboard/start_viewer.cmd`：本机查看三个市场页面，只读已发布快照。
- `dashboard/start_demo.cmd`：合成演示，不修改真实数据来源。
- 原生依赖在 `.deps/dashboard_native`，环境可通过 `SWHY_DELTA1_PYTHON` 指定。

```powershell
cd P:\project\swhy\Delta1\project
& 'P:\code_content\python_work_env\conda_env\swhy_delta1\python.exe' -B -s -m dashboard
```

重复启动激活已有窗口，开发与市场入口可同时运行。通信通道不可用时仍打开窗口。
恢复入口为 `start_app_recovery.cmd`，日志在 `runtime/startup`。
这是 Python 桌面 App，尚未构建免安装 exe。

## 页面

| 页面 | 功能 |
| --- | --- |
| 股指期货概览 | IF/IH/IC/IM 卡片与矩阵；基差、跨期、β/R²/残差、波动；同指标叠加及单品种详情、期限结构 |
| 专题与自定义指标 | 同期限跨股指基差差与收益回归；持有成本及 ETF 接入状态；四品种公式结果与版本 |
| 市场异动 | 基差、跨期、回归偏离；连续 3 根超 2σ 确认、持续合并、恢复和历史观测；事件依据图 |
| 公式工作台 | 受限 Python、多频与盘口输入；试算、发布、启停；新结果自动加入看板 |
| 数据与任务 | 数据校验、各类路径、独立采集调用；生成独立公开 Git |
| 结果档案 | 版本、合约、来源与截止时刻；SQLite 及按日期不可变 Parquet |

图表支持缩放、拖动、悬停及勾选单个品种。工作台保留私有回放滑块和 1/5/10× 速度。
分钟与秒级图仅保留北京时间 09:30–11:30、13:00–15:00，午休、隔夜和无观测交易日折叠。
四条曲线共用时间映射；交易时段内缺数仍保留，悬停显示原始时刻。日频按观测交易日等距展示。
打开应用不自动采集，也不使用原有商品期货或境外市场数据库。
指标口径与交易所资料见 [MARKET_INDICATORS.md](native/MARKET_INDICATORS.md)。

## 对外交付与后续开发

生成整套阶段交付：双击 `dashboard/build_releases.cmd`，或在「数据与任务」点击 **生成全部阶段稿**。
它从当前共享源码与同一份新计算的合成快照生成以下内容：

| 内部阶段 | 对外交付名 | 内容 |
| --- | --- | --- |
| 20% | 指标样稿 | Excel：四品种基础指标、可编辑价格与计算公式、原生图表、口径说明 |
| 50% | 桌面原型 | 单页概览、分钟数据、基础基差与跨期指标、手动刷新 |
| 80% | 联调稿 | 三页面、日频与分钟、回归和自定义结果、基础异动列表、手动刷新 |
| 1.0 | 1.0 | 三页面全部交互、秒级、详情图、事件依据与自动刷新 |

各阶段在自身范围内同步后续改动，范围外的新功能不会进入较早阶段。
输出在 `dashboard/outputs/<任务标识>/<批次时间>/`，其中 `latest.json` 指向最近成功批次。
每次新建一批，保留旧交付；只向接收方发送相应目录中的 Excel 或 Git bundle / ZIP。
内部清单、其他阶段目录与本项目源码不属于对外交付。
阶段交付和恢复说明见 [STAGED_RELEASES.md](native/STAGED_RELEASES.md)。

在「数据与任务」点击 **生成看板发布 Git**，或执行：

```powershell
python dashboard/build_public_repository.py --demo-file "dashboard/runtime/published/demo.json" --bundle
```

生成目录 `dashboard/runtime/distribution/Delta1-market-dashboard` 有独立 main 和公共历史。
bundle 可离线交给接收方克隆；公开标题、源码及历史没有版本关系，排除父项目历史和私有功能。
页面唯一源是 `native/market_view.py`，主题源是 `native/theme.py`。
后续改共享源再构建，公开 Git 跟随；自定义指标结果通过快照自动更新。
操作见 [内部维护](native/EDITIONS.md) 与 [发布说明](native/PUBLIC_RELEASE.md)。

默认发布到 `runtime/published`，对外通过 `--publish-root` 或 `DELTA1_DATA_ROOT` 指定可读目录。
每次四品种 × 日/分钟/秒共 12 个视图，同频四品种使用同一快照。
心跳、盘口与行情时刻分别校验；历史行情保持历史标记，合成示例始终标为演示。

## 图标与检查

窗口、任务栏与快捷方式使用 `assets/delta1.ico`，同目录保留 SVG、PNG。
移动项目后可运行 `update_shortcuts.ps1` 重建入口；附加 `-UpdateDesktop` 更新本项目桌面快捷方式。
旧选型原型保存在 `analysis/2026-10-01`，本次截图位于 `analysis/2026-10-02/public_*.png`。

```powershell
python -B -s -m unittest discover -s tests -p 'test_native*.py' -v
```

2026-10-01 的 44 项验收是历史记录。本次新增回归、三页面、公共 Git 历史和 bundle 独立启动校验。
数据规范见 [data_contract/README.md](data_contract/README.md)，旧网页参考见 [legacy_web_README.md](legacy_web_README.md)。
