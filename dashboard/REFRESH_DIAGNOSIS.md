# 数字 Excel 刷新证据与版本对照

核对日期：2026-10-20（北京时间）。刷新修复已发布为 `60e5446`；公司11:06返回诊断，确认实际运行此版本。本次精简界面是在该版本之后实现，公司需更新后测试。

后续实施已获用户授权：统一分支新增精简概览、25项指标页、原生图表及历史/网络向导，使用见 [NUMERIC_EXCEL.md](NUMERIC_EXCEL.md)，更新见 [COMPANY_SETUP.md](COMPANY_SETUP.md) 顶部。诊断同时读取window.view及overview_match_feed，按当前选择档位核对可见卡片；跨一次后台发布仍报告不可判定。公司最新具体HEAD依然仅有此前60e5446证据，本次新界面、DDB授权与真实补齐待实机反馈。下表为历史版本对照，U的新增功能以下表补充为准：

| 项目 | 本次状态 | 公司更新 |
| --- | --- | --- |
| U数字Excel及必要历史后台 | codex/company-apps；精简界面和向导已实现；新增内容只在U，旧O不改 | pull后原入口打开；DDB可后配 |
| O展示版/开发版 | a070339加原未提交内容，未复制或推送前端 | 本次不安装新App前端 |
| 原离线代码包 | company-apps-numeric-refresh-20261020.bundle仍为60e5446，不含新界面 | 在线优先pull，不能用旧包声称更新 |
| 独立短数据包 | 历史分片内容未修改；10/16截止的包不因界面更新重导 | 可选DDB增量补齐；不覆盖整个data |

后续用户反馈“看到可以了”，并指出B04.Q/B10的日期仍为10/16、B09/B11缺失；尚无新的两次公司实时诊断。已进一步核对历史包与本地历史，原因分解及用户已认可的启动/精简首页方案见 [EXCEL_UX_PROPOSAL.md](EXCEL_UX_PROPOSAL.md)。原评审阶段未改启动器/模板；本次已实施，不要求重复导入相同数据。

## 已确认与未确认

最初公司返回 `2938763`、只读命令及文件路径，只能确认当时版本与启动方式。随后用户返回11:06:46的一份公司诊断：HEAD为 `60e5446`、统一分支，实际后台Python确为 `D:\conda\envs\swhy_delta1\python.exe`。运行号 `a55c931f` 对应11:04:12生成的工作簿，原生窗口FullName/HWND/PID与启动记录一致，attached/visible/window_enabled均为true；代表单元格与feed一致，saved=true，最后成功保存于11:06:42，无已记录错误。这已确认本次检查的是启动器维护的同一可见工作簿。

当前数值不变的直接证据是 `read_only_cache=true`、`collect_requested=false`、`collector=idle`，且配置指向的 `data/market/index_futures/dashboard/realtime/live/quotes.sqlite3` **不存在**。该运行没有主动采集，也没有从此实时库获得新行情；feed原始时点和窗口A4均为北京时间2026-10-16 15:00，K7明确为“历史收盘”。它正在基于导入的历史数据重算，不能用计算/保存时间当行情时间。这里只确认当前配置指向的库，不推断公司其他目录是否另有采集程序。

公司配置使用 `dashboard/localsetting/numeric_excel/native.json`，history_roots为 `data/market/index_futures/dashboard/imports/20261019_short/` 下的index/futures，reference_file为该导入目录的reference.json；分红目录仍指向现有inputs。本次诊断没有证明路径配错，也没有要求重新导入或改配置。诊断输出只返回了一份样本；公司新行情到达后同一窗口随之变化、持续采集和长时间运行仍未验收。下一步直接在公司行情网络可达且时段允许时，以不带 `-ReadOnlyCache` 的入口运行，再用新运行的两次样本核对源时与单元格。

`calculation.ready=false` 与 `feed.ready=true` 同时出现不表示结果失效：前者是独立进度文件，可能采到档位处理阶段，后者表示完整结果已发布；两文件分开读取，非原子快照。此样本进度更新时间早于feed完成时间。窗口状态约30秒更新，因此A4计算时间比最新feed稍早也不等于写入故障。

本次确认的代码问题与处理：

- 旧 A4“已更新”使用计算开始时点，每轮生成时间变化都会整表写入、保存，容易被误读为新行情。现在区分计算完成、原始源时、写入、保存、运行检查；相同结果不重写指标表，状态约30秒更新和保存一次。行情内容变化立即写入，不改计算/分位口径。
- 旧模式文字仅说明是否处于行情接入时段，没有清楚说明只读缓存。现在显示实际采集模式、时段守卫、首次读取/源时与报价是否变化。输入变化也不直接称“新实时行情”。
- 每日缓存原来跨配置复用。数字服务现在核对数据配置标识，未标识或来自另一配置的旧缓存不作启动/行情回退依据；旧文件保留，从配置指向的原历史/行情重新计算。数据源、分红模式、allow_unverified 均进入标识，凭据不进入。
- 旧版没有可追踪的窗口和运行身份。现在记录运行号、实际 Python、配置路径、输出/Feed 路径、进程、显示后的工作簿 HWND、回读单元格和成功保存时点；窗口显示运行号与文件路径。打开后 HWND 可能变化，因此以显示完成后的工作簿窗口为准。
- COM 拒绝调用或通用写入/保存错误会保留错误状态并重试。文件被占用可能导致 Excel 在 `Save()` 内弹出模态对话框，即使 DisplayAlerts=false；在调用前记录 `saving`，只读诊断识别被禁用的工作簿窗口，不能称已保存。需要人在该 Excel 中处理对话框；不承诺这种 Office 状态可自动恢复，不自动关闭对话框或用户工作簿。

## 如何判读一次运行

| 层次 | 证据 | 不能据此推出 |
| --- | --- | --- |
| 后台循环 | 两次 feed 的 generated_at/计算完成时间、ready、运行心跳 | 行情已更新 |
| 缓存到达 | 同一个 SQLite 的 sequence、received_at、源时 | 新成交或同步有效报价；重复源快照也会新增记录 |
| 展示输入 | 各合约期货/指数原始源时、价格、显示类型 | 历史回退或合约切换就是新实时行情 |
| 指标计算 | 完整结果、计算完成时间、代表行；各指标自己的时点 | 日线/OI指标应每3秒变化 |
| 工作簿写入 | 同一 FullName/HWND/PID 的 COM 单元格回读 | 已保存到磁盘 |
| 保存 | last_save_at、文件 mtime、saved；状态不是 saving/write_error | 用户正看这个实例 |
| 用户可见窗口 | 窗口运行号、原生可见性、实际单元格与 feed 对照 | 用户目光位置；仍需认对运行号 |

09:29前、15:01起、休市和未知日历继续不新接入行情。缓存保留原始时点，不保证是最终收盘价。缺失留空，合法0保留。数字看板 L 列为展示定位时间；期货和指数各自的原始源时在“来源与状态”中分别列出；研究指标继续使用各自的频率与时间。

## 公司按顺序更新与核验

以下先记录 `60e5446` 当时的接入验证方式；取得本次精简界面需先按 [COMPANY_SETUP.md](COMPANY_SETUP.md) 顶部更新。要接入盘中行情，先关闭原数字Excel并等待启动终端退出，保留其他Excel；在公司行情网络可达时执行以下命令。启动器仍受09:29/15:01时段守卫和网络互斥约束。

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
$env:SWHY_DELTA1_PYTHON = 'D:\conda\envs\swhy_delta1\python.exe'
.\dashboard\start_numeric_excel.cmd
```

原缓存目录可保留；采集器通过检查并实际启动后会创建所需实时库，无需手工建SQLite或搬数据。启动后按下面的另终端诊断命令获取新运行样本，默认选最新活动运行；若有多份，用新窗口运行号，不能沿用a55c931f。希望看到采集运行、缓存存在且源时更新、同一窗口单元格与feed相符；仅collector=running或sequence增长不等于报价新鲜。

以下为代码更新的通用步骤。先停止本次数值Excel运行；若Excel有保存/编辑对话框，先在该窗口处理。普通更新不需要重导任何数据包，也不覆盖data或配置；本次完整启动步骤以COMPANY_SETUP顶部为准。

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
git status --short
git branch --show-current
git log -1 --oneline
```

有源码修改先保留并处理冲突；本次公司已确认在统一分支，无需切换。

```powershell
if ((git branch --show-current) -ne 'codex/company-apps') { throw '分支不符，停止并保留现场' }
git pull --ff-only origin codex/company-apps
if ($LASTEXITCODE -ne 0) { throw '更新失败，停止；不要强制覆盖' }
git log -1 --oneline
$env:SWHY_DELTA1_PYTHON = 'D:\conda\envs\swhy_delta1\python.exe'
if (-not (Test-Path -LiteralPath $env:SWHY_DELTA1_PYTHON)) { throw '已有 Python 路径不存在；请用实际环境路径，不要重装' }
& $env:SWHY_DELTA1_PYTHON -c "import sys,pyarrow; print(sys.executable); print(pyarrow.__version__)"
if ($LASTEXITCODE -ne 0) { throw '原环境检查失败，保留输出诊断，不继续' }
.\dashboard\start_numeric_excel.cmd -ReadOnlyCache
```

启动后保持这个窗口和终端。另开 PowerShell，在同一公司仓库根目录执行一次（只读；不准备/激活配置、不创建采集器、不打开另一份 xlsx）：

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
& 'D:\conda\envs\swhy_delta1\python.exe' -B -X utf8 -m dashboard.numeric_diagnose --samples 2 --interval 10
```

默认寻找最近仍有心跳的运行；有多份时加 `--run-id 窗口显示的8位运行号`。只需返回该命令的输出，并确认窗口运行号相同，不需要整份 Excel、数据库或配置。它报告仓库 HEAD、实际生产 Python 与诊断 Python、路径差异、缓存尾记录、两次 feed、原生窗口单元格、保存时间。`cells_match_feed=null` 表示采样期间后台发布了另一轮，不能当写入错误。旧运行没有 run.json 时需更新重启，诊断不会猜测或另开快照。

若只读模式两次缓存 sequence 和源时均不变，Excel 值不变正常；希望盘中持续采集，应在客户端连好公司行情 VPN，关闭本次只读窗口后运行不带 `-ReadOnlyCache` 的原命令。HTTP实时源与 Wind 历史库是不同来源，正常命令仍受09:29/15:01守卫及网络互斥约束；连接成功也必须核对逐行新鲜度。

## 实际版本对照

路径缩写仅用于表格：

- **U** = `P:\project\swhy\Delta1\company-apps-worktree`
- **O** = `P:\project\swhy\Delta1\project`
- **C** = `D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard`（公司仓库根）

| 项目 / 实际位置 | 分支或包头 | 入口 | 配置 / 数据来源 | 已核验 / 未完成 | 推送及公司更新 |
| --- | --- | --- | --- | --- | --- |
| 旧展示版 `O\dashboard` | `codex/dashboard-history-release-20261019`，HEAD `a070339`，前端未提交 | `dashboard\start_presentation.cmd` → `native.editions_current` | `dashboard/localsetting/native.json`；其 history_roots/realtime_root、合约参考与分红设置 | 代码确有四品种卡片、四档选择、分位/n、六项指标、实时启停、数字快照；本次只核对源码，未进行新的 App 实机验收 | 新前端未推送；本次旧目录491个原有未提交文件与95份配置/保护文件按哈希核对，不覆盖。公司不安装新前端 |
| 旧开发版 `O\dashboard` | 同上 | `dashboard\start_development.cmd` → `DeveloperWindow(ResearchWindow)` | 同上 | 已继承研究窗口并增加数字快照导出；诊断溯源统一状态仍待方案实施 | 同上，暂不发布 |
| 数字 Excel `U\dashboard` | `codex/company-apps`，刷新代码 `60e5446`，后续HEAD含说明更新 | `dashboard\start_numeric_excel.cmd` | 默认 `dashboard/localsetting/numeric_excel/native.json`；首次复制已有配置，既有副本不覆盖；输出默认仓库data，计算缓存使用共享DATA_ROOT | 本机合成/实连验证见下；U默认数字配置并不存在，验证使用隔离副本 | 仅白名单代码/测试/说明发布统一分支 |
| 公司实际数字 Excel `C\dashboard` | 用户11:06诊断确认 `60e5446`、`codex/company-apps` | `-ReadOnlyCache` | 数字专用配置；短包index/futures历史；实时根为C下 `data/market/index_futures/dashboard/realtime`，其SQLite不存在 | 实际Python、同一可见窗口、代表单元格匹配与保存已确认；当前显示10月16日历史收盘。公司实时采集及新数据变化仍待核验 | 已确认此次代码更新；下一步改用允许采集的原入口，无需重新pull或导数据 |
| 共用计算/数据后台 `U\dashboard`、`U\index_strategy\instant_dld` 与 O 的同名目录 | 公司基线1ec44ed、短名240a995、性能9d4deb0；两分支非快进关系 | numeric_excel / display_snapshot / NativeModel / CollectionJob / RealtimeReader | 当前入口决定配置根；不是全局同一份 native.json | 短路径7个文件、bars/nonregression在本次前已同步旧目录（两文件仅换行差异）；旧 numeric_excel 保留原配置解析。旧 live.ps1 缺61a5f42/2938763；本次状态/配置隔离修复仅U。contracts/service另有旧分支夜盘交易日和连接探测功能差异，未整体复制 | 仅公司版本更新；O仍原样保留。不要用目录同名推断字节或功能相同 |
| 离线代码 `U\dashboard\runtime\distribution\company-apps-numeric-refresh-20261020.bundle` | 代码修复包头 `60e5446`；前提 f8c1d2f；不含后续公司诊断说明提交 | Git bundle；非解压安装包 | 只含Git代码/测试/说明；不含本机配置/数据 | 已通过list-heads/verify和隔离导入，导入树与60e5446一致；240,861字节 | 包本身不上传Git；在线公司优先pull，不切旧分支 |
| 独立私有数据 `U\dashboard\runtime\distribution\dashboard-data-short-v2-20261019.zip` | 非Git；75,655,652字节；SHA256 `878548493cdbe5dcdcb18b79c5cab33c3eb4a1e127b0fb99f418cabda38eac96` | 缺数据/确需迁移时显式 data_package 安装器 | 历史/分红/参考增量包；不含当前实时更新、凭据 | 文件及校验已核对；本次不重装。公司当前启用哪套数据以诊断配置为准 | 不推送；与代码包分开，绝不解压覆盖公司整个data |

另有 lending-worktree（`codex/securities-lending`，`066f176`）和 script-making-worktree（`codex/script-making`，`58e3194`），本次只读核对，不作为数字版更新入口。工作区状态以 `.deps/numeric_refresh/` 本机审计记录及当前 git status 为准。

原公司/旧看板共同祖先是 `003c2e3`；本次前双方独有提交为88/9，不能把旧分支直接当统一分支快进。旧目录 `NEXT_CHAT_PROMPT.md`、`PROJECT_HANDOFF.md`、`COMPANY_CHECKLIST.md` 中“仅推历史看板分支”“导入旧包”“暂不推送”等历史语句不再适用于公司日常更新；原文保留作历史，本说明及根 AGENTS 优先。旧 `dashboard-code-20261019.bundle` 包头a070339、numeric包1ec44ed、shortfiles包240a995、startup包9d4deb0、status包61a5f42、visible包2938763均不能代替本次修复。旧长名数据ZIP也不是本次要求重导的理由。

## 验证边界与后续优先级

本地合成验证覆盖时段/休市不联网、不同配置缓存隔离、同一模型读取新SQLite记录、同一可见工作簿FullName/HWND/PID、源时与价格单元格变化、磁盘保存、缓存不变不重复保存、零与空值、保存阻塞识别及选中单元格/滚动位置保持。文件占用测试仅确认等待诊断，未把强制结束合成测试进程说成自动恢复。对应后台回归71项通过；实际Excel四项通过（一次测试清理的文件锁错误修正后定向复验）。证据保留于开发机 `.deps/numeric_refresh/`，不上传真实数据。

本机既有保存数据在隔离配置下重算，16/64/400三张结果表与旧格式化函数在相同冻结输入上逐格一致；连续重算保持原源时，原SQLite哈希不变。

用户随后授权本机 VPN 实连验证。北京时间2026-10-20 10:37完成独立人工诊断：最多三轮，每轮20个标的全部返回，按正常客户端和存储器写入独立诊断缓存，仍用原计算引擎及同一个可见Excel窗口。三轮原始源时范围依次为10:37:10–13、10:37:27、10:37:34–36；同一FullName/HWND/PID的价格、数据时点和计算指标单元格与feed相符，最终磁盘文件也回读一致。停止采样后重算相同缓存，窗口明确显示“未观察到源时/报价变化；重算不代表新行情”，原始源时保持10:37:34–36。原行情SQLite哈希未变，真实行情、成品和诊断证据仅留在忽略目录 `.deps/numeric_refresh/`，不进入提交。

这次实连采用具体合约、有限三轮采样和隔离缓存；没有启用长期采集或改写原有数据/配置，不等于完整启动器自动换月流程或公司电脑实时验收。公司11:06样本随后确认了实际Python和当前可见窗口，但HTTP访问、新行情输入后的连续变化、长时间运行、筛选/编辑交互仍待验证；Wind实连未测试。自动回归、本机VPN人工验证、公司只读运行三类证据分别报告。

1. **P0 本次发布：** 刷新证据、窗口身份、缓存配置隔离、减少重复写入与诊断已发布；公司只读样本已定位缺少当前配置的实时缓存输入。接下来验证正常入口采集与新源时进入窗口；不盲目安装、改路径或搬数据。
2. **P1 Excel可评审方案：** 沿用四张表，把固定顶部状态收敛为采集方式、行情时点、计算/保存、运行身份四项；四档分组阅读，核心F/S/D/T/年化固定，分位与n相邻；缺失原因用短标记及可查明细。先做一份合成样例供评审，再调整列宽、分组/冻结、筛选范围。验收要覆盖用户实际滚动、筛选和编辑，不用时间戳或颜色闪动充当行情更新。本次不重排指标或改变样本口径。
3. **P1 共用状态协议：** Excel和两个App共同使用行情源时、接收时、计算时、缓存身份、日历守卫与数据可用性解释。现有display_state、session_clock已共用；新增运行证据目前只有数字版接入，前端接入是待办。
4. **P2 展示版方案：** 保留现有四卡及六指标，优先展示关键值、分位/n和影响当前阅读的异常，详情展开显示数据来源和缺失原因；不把全部调试表铺在首页。现有卡片/六指标已在源码实现；统一状态摘要和异常层次仍待实施/评审。
5. **P2 开发版方案：** 保留现有ResearchWindow功能，增加按一次运行联查配置来源、源时/接收时、缓存sequence、历史版本、指标依赖与缺失原因；复用现有冻结快照/percentile_audit，明确“原反馈复现”与“新测试”。前端仅本地修改，评审后才实施，继续不提交/推送。
6. **P3 性能方案：** 在源版本、行情内容、交易日/新鲜度边界、分红变化的完整失效条件明确后，再讨论跳过重算；当前仍按约3秒目标重算（耗时顺延），只减少重复Excel表写入，避免通过粗暴缓存掩盖新行情或到期变化。
