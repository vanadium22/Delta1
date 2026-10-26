# 2026-10-26 指数 / ETF 新概览验收

本轮按用户已确认蓝白草图改版指数和ETF，期指及第六版公式保留。本机离屏验证不等于公司通过。

在本文件原公司Git根目录执行git pull --ff-only，重开原dashboard/start_presentation.vbs。核对：

1. 指数页四卡、行业贡献及权重、行业内个股明细显示；点指数及行业后身份一致。缩放至860/1100/1440/1920宽度并纵向滚动，无覆盖或横向截断。
2. ETF切四指数，每组最多三只规模卡。排名需完整同指数同日规模资料，显示日期；未取得时明确待核验，原代表不冒充规模第一。
3. 盘中看主卡源时间推进，行业分钟快照约60秒更新，二者与页面刷新时间独立。报价缺失显示覆盖率；权重早于准确昨日时贡献留空，不冒用周度旧权重。跨日权重滚动尚待后续实现。
4. IOPV先核验现有源；无字段/映射时待接入。缺IOPV、历史或成分行情均不拖住主价。申赎、成交额未核验的单位和日频资料不能显示假值。
5. 正常入口每周后台核验一次Wind低频资料；不自动切任何VPN，不安装或升级Wind。连接/字段/单位不齐时保留原快照并留缺数。本机此次未取到真实Wind资料，公司结果待回传。

在**原Git根目录**运行：

```powershell
.\dashboard\diagnose_presentation.cmd -Overview
```

回传输出目录的overview.json和diagnosis.json；如overview_exit_code非0，再附overview.stderr.log。此命令只读已有库/原始响应字段名及两次源时、规模/权重/覆盖/Wind状态；不发接口请求、不改VPN、不启动第二个看板，不需要为了诊断额外连接VPN。正常看板的行情连接仍按原网络可达性及手动实时VPN规则处理。两样本只用于排查，不证明10–15分钟持续运行。

# 公司展示版：第一阶段交付与现场测试

13:07公司报告已看到多个早于ETF版/接管版发布的旧App进程，网络锁文件唯一登记使用者也是旧展示版。更新后必须重开原VBS触发接管；旧进程不会因git pull更新。-Routes现可在DNS缓存为空时，用核验看板进程在行情端口的现有TCP连接查询实际所选网卡/网关，仍不发网络请求。无当前连接或读取受限时继续明确缺证据，不操作VPN。

## 2026-10-26 重复打开、ETF与公司网络检查

最新反馈为App已打开，但新窗口取得网络锁时报errno13，指数源时仍推进，ETF四卡无数值。当前修复加入安全替换同数据范围旧App、旧版正常关闭兼容、明确采集归属、ETF无观测提示和锁操作阶段。公司真实锁持有者及网络路径仍待报告；本轮不提前扩展指数/ETF概览布局。

1. 在原Git根目录执行 `git pull --ff-only`，重开原 `dashboard/start_presentation.vbs`。正常实时入口会先请求旧看板退出，等待采集/计算/写入结束后接管。慢任务可能需要等待，超时新窗口只读；Excel和其他项目不会关闭，不删锁或强杀。
2. 核对旧看板退出、顶部“本窗口持续采集”、ETF四卡报价及“行情源”时间推进。显示“读取已有行情 · 本窗口未采集”仅证明现有库有新观测，不能证明本窗口采集成功。
3. 公司网络可直接访问行情源时不需要额外连实时VPN，程序验证当前连接后直接使用。程序不自动操作实时VPN或为实时重试切回DDB。不要为了判断是否直连而主动断开正在使用的网络。
4. 核对公司实际网卡/网关与锁使用者，在原根目录运行 `.\dashboard\diagnose_presentation.cmd -Routes`。输出目录的connection.json包含所选App配置、锁文件访问/使用者、当前DNS缓存目标IP的所选路由与网卡；不发DNS/TCP/HTTP、不改路由/VPN。无法读取时明确unavailable，不推断“公司自带VPN”。公司网关内部是否使用专线/VPN仍需网管信息。

如需单独有限接口测试，先在看板暂停本轮采集，确认无历史任务，再显式使用 `diagnose_presentation.cmd -Routes -Connect`；该可选参数才会请求行情。默认及仅-Routes均不联网。诊断默认优先实际App配置，可用-LocalRoot选原配置；不重新录入或导出凭据。

## 2026-10-26 最新概览验收

本次已按用户要求新增市场概览的指数/ETF/股指期货三子页，展示入口默认public蓝白。页面、口径和数据边界见 [APP_MARKET_OVERVIEW.md](APP_MARKET_OVERVIEW.md)。下文早期“随后再优化概览”的阶段限制不适用于本次明确授权。

公司先 `git pull --ff-only`，重开原 `dashboard/start_presentation.vbs`。若点击无窗口，在原仓库根目录运行 `.\dashboard\diagnose_presentation.cmd`，保留输出目录的 `diagnosis.json`、`preflight.json` 及最新 `run-<PID>` 日志；不要重录凭据、删除锁或重置数据。

本轮重点：四指数卡片、四只代表ETF、期指品种与月份筛选；放大/缩小窗口与滚动无覆盖；源时间推进且页面时间独立；缺今日日线时最新价/源端昨收涨跌继续显示；缺IOPV仅折溢价留空，缺前20日仅分位留空。盘中手动连接实时VPN后观察10–15分钟，联合诊断中的请求、落库序号、计算和页面应用检查持续更新。缺历史仍按原规则自动DDB；实时重试不切回DDB。

当前开发机获准的四轮真实HTTP读测已收到4指数/4ETF/16期指，未改VPN、原数据或配置；此结果不代表公司电脑启动、DDB补库或长期运行通过。

本版先交付现有 App 和数据更新流程。Excel 冻结功能维护，历史源码、模板、成品、数据、分红、缓存、配置全部保留。不要结束仍在使用的 Excel 或其他采集器。本机离屏回归不能代替公司盘中实测；11:07 的有限连接成功也不能证明持续更新。

## 更新与首次依赖检查

公司这个路径本身是 Git 根目录，内部另有 `dashboard` 源码目录：

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
git pull --ff-only
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\dashboard\prepare_app.ps1
```

检查默认复用 `D:\conda\envs\swhy_delta1\python.exe`。显式 `SWHY_DELTA1_PYTHON` 优先，其次公司环境、仓库 `.venvs/dashboard_app`、仓库 `.venv`、已存在的本机环境、PATH。不会升级 Wind 环境。

如果报告仅缺 Qt/pyqtgraph，执行一次：

```powershell
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\dashboard\prepare_app.ps1 -InstallGui
```

UI 包固定版本安装在仓库 `.deps/dashboard_native`，`--no-deps` 不升级现有数据依赖。完整新环境依赖清单为 `requirements-app.txt`，已有公司环境不应整包覆盖安装。历史 SDK 若缺失，可在 App 内指定已有的历史 Python，或由环境维护人按该清单补齐；等待 SDK 时仍能看已有数据。手动检查报告在 `dashboard/runtime/app_startup/preflight.json`；每次打开 App 的报告和日志独立保存在 `dashboard/runtime/app_startup/run-<PID>/`，无密码。没有出现主窗口时先看最新的运行目录，不会弹出安装或错误对话框。

日常双击 **`dashboard/start_presentation.vbs`**。它隐藏启动控制台，只显示 App 主窗口。命令行或现有快捷方式也可调用 `dashboard/start_presentation.cmd`。两者走同一入口，不依赖 Excel/COM 或开发版。

已修复 Windows PowerShell 将 Python/Qt/采集器的 stderr 普通提示当作致命错误、中断 App 的问题。启动器现在直接隐藏启动子进程，将普通输出和错误输出分开写入 `.log` / `.stderr.log`，不因提示日志结束 App。`run-<PID>/launcher.json` 记录启动阶段和真实退出码，Python 原生崩溃栈也尽可能保存在 stderr 日志。

如果更新后仍自行关闭，先保留最新 `run-<PID>` 目录。`launcher.json` 的 `phase=app_exited` 表示已观察到子进程退出，`exit_code` 为其真实代码；`launcher_failed` 表示启动器自身失败。`app_running` 是启动时记录，不能独立证明进程仍存活。正常日常入口没有15秒或3分钟自动关闭规则，自动退出只用于显式离屏测试参数。公司日志与下面的持续更新报告一起用于定位，不重新录入密码或删除数据试错。

## 数据与自动连接

已有 App 专用配置优先。没有专用配置时，从已验证的 `localsetting/numeric_excel/native.json` 创建一次 App 副本，保留全部公司路径；没有数字版配置的旧本机 App 继续原 `localsetting/native.json`。原配置不覆盖。DDB/VPN 凭据保留原引用，不复制密码，不迁移或重置保护方式。显式 `--local-root` 可选已有配置。

主窗口立即可操作，现有数据在计算线程加载。后台先做发布/覆盖元数据快检，再检查近期三交易日、已知缺口和已变化分片；已核验且身份未变的旧分片复用证据。初次没有新格式覆盖账本的旧历史标明“尚未深核”，不会把旧 0 缺口当新验证。完整历史逐分钟核验通过“数据更新 / 设置 / 诊断 → 完整深核”运行，可取消。

**DDB 自动、实时 VPN 手动。** 有历史缺口时，先检查 DDB 网络；网络已通直接复用，否则自动连接数据 VPN，再用已保存的数据库账号密码补到上一交易日，校验并共同发布。有进展且到期的部分批次自动续批。没有缺口不会为了检查而登录 VPN。数据库账号与 VPN 账号分别读取；前者不能代替后者。

自动数据 VPN 复用公司原 `history_vpn_config`、`history_vpn_trust`、`history_vpn_powershell` 引用；旧 App 副本未保存引用时只读查找原 `numeric_excel` 配置，不重写它。需要当前 Windows 用户可解密的 VPN 凭据、已信任的网关证书、已安装的深信服客户端和 PowerShell 7。路径可在内联设置核对。缺配置、证书不匹配、密码不可用或需要验证码/二次认证时停止自动登录并说明原因；不绕过证书、不弹旧配置向导。显式保留的 `history_vpn_mode=manual` 仍禁止自动登录，默认是 `auto`。

历史会话和登录辅助进程真正退出后，App 有限验证实时接口；若已连通，直接持续采集。若未连通，仅**交易日北京时间09:30（含）–11:30（不含）、13:00（含）–15:00（不含）**弹窗请你手动连接实时VPN，午休、盘前、盘后及休市不弹。你在 VPN 客户端手动切换后，点**“已连接，验证并开始”**；再次验证成功才开始持续采集。选择**“稍后连接（只读）”**则本轮停止自动更新，不反复提醒；之后可在主窗口点“验证并开始实时”。程序不自动退出 DDB VPN、不自动操作实时 VPN，也不会因实时重试而自动切回 DDB。实时失败不会每30秒重复弹窗，同一时段自动提醒至多一次。

“历史任务退出”不必然代表历史全部补齐；请同时看历史状态及剩余缺口。补库失败或未深核时保留原因和缓存，实时仍可按上述流程独立接入。需要继续补历史时主动点“重试历史”，新一日空闲时也会重新检查。

除获准的盘中实时VPN提醒外，设置、路径、数据库账号、进度、取消、重试、公式和诊断都在主窗口。需要更换数据库凭据时在内联设置保存一次，留空密码保留已有值。不会要求从家里复制当前用户加密的密码到公司。改设置前先停止本轮后台并等待完成。旧任务持锁时保留缓存与诊断，不删除锁、不强杀进程。

## 公司请先测试这五项

1. 只打开展示版：解释器、两类历史目录、参考文件、实时目录和分红均指向公司原路径；不需要 Excel/开发版，没有模态向导。
2. 有数据先显示，快检不阻塞主窗口；存在历史缺口且DDB网络不通时，观察“自动连接数据VPN → 认证 → 增量补库 → 校验/共同发布”，已有连接则跳过登录。诊断 `history.ddb_vpn.mode=native_login` 表示本轮自动登录，`existing_tunnel` 表示复用，`state=not_needed` 表示没必要连接；还要看历史目标、剩余缺口和发布状态，不能只凭VPN已连接判定补库完成。缺SDK、凭据不可解密、认证失败、网络不可达分别显示原因。未知/未深核不报完整。
3. 盘中历史任务退出且实时未通时，应出现手动连接提醒；手动切好VPN，点击确认后，核对 **持续采集正在运行、有效数据序号递增、源时推进、计算完成、页面已应用版本**。连续观察10–15分钟；再测试“稍后连接”后保持只读、不重复弹窗。午休/盘后不弹窗；实时已经可达则不必提示。09:29（含）至15:01（不含）的既有实时接入门控、逐行源时/质量、缺腿与同步规则保留；提醒窗口更窄。休市只能验收可用性和正确状态。
4. 测试概览/对应指数、期现/跨期/跨品种现有指标，切换合约、参数、输入 X；打开详情图像和解释/公式。切换后旧任务不覆盖新选择；计算慢时保留明确标注的上一结果，队列最多一个执行和一个最新待处理请求。
5. 断网再恢复、取消/只读、手动重试和关闭重开。关闭会等待本轮采集和历史写入正常结束；不误停其他用户任务。两个 App 可读同一库，但互斥锁只允许一个网络写入者；另一窗口明确等待并读取缓存。

## 有时间上限的诊断

窗口的“导出诊断”保存到该实例 `dashboard/runtime/app_sessions/<运行号>/report-*.json`，路径直接显示在窗口。报告包含源时/接收时间、持久化序号、缓存读取、计算开始结束、页面应用时间、队列和失败阶段，不含密码。`network_policy=auto_ddb_manual_realtime`、`history.ddb_vpn` 和 `awaiting_realtime_vpn` 记录当前流程；登录失败/取消后的 `vpn_changed=null` 表示无法确定隧道是否改变，需看客户端，不能误读为未改变。

需要观察一段时间时，在 Git 根目录运行（15 秒自动退出）：

```powershell
& 'D:\conda\envs\swhy_delta1\python.exe' -B -X utf8 -m dashboard.app_diagnostics --seconds 15 --output .\dashboard\runtime\company_app_15s.json
```

盘中保持 App 正常运行，执行完整15分钟诊断命令：

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
& 'D:\conda\envs\swhy_delta1\python.exe' -B -X utf8 -m dashboard.app_diagnostics --seconds 900 --output .\dashboard\runtime\company_app_15min.json
```

最大15分钟，每3秒采样；诊断工具本身不会发网络请求、打开窗口、操作VPN或进程，App仍按当前模式运行。比较 `collection.data_sequence` 与 `applied.realtime_sequence`，再看 `source_times`、`cache_read`、`calculation_seconds`、`ui_applied_at`，可以区分源端陈旧、请求失败、历史占用、读错目录、计算耗时和界面回填。序号递增并不等于源行情新鲜，源日期仍按原接收日推定，质量限制继续生效。

当前状态：**待公司实测**。请先回传主要功能和持续更新反馈；等待期间只修运行/更新问题。指标重构须同时满足公司反馈、你明确继续、最新指标 doc 到位；美术细化也留到公司主要功能实测之后。
