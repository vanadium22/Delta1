# 公司展示版：第一阶段交付与现场测试

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

已有网络可达时自动复用本机 DDB 凭据补到上一交易日，校验并共同发布；部分批次有进展且后续任务到期时自动续批。历史进程真正退出后，有限验证实时接口，再启动持续采集。程序不登录、切换或退出 VPN。网络需要变化时由你操作，窗口保留具体等待/失败阶段；点击“验证并开始实时”也会先等待历史任务安全收尾。

所有设置、路径、账号、进度、取消、重试、公式和诊断都在主窗口。需要更换凭据时在内联设置保存一次，留空密码保留已有值。不会要求从家里复制当前用户加密的密码到公司。改设置前先停止本轮后台并等待完成。旧任务持锁时保留缓存与诊断，不删除锁、不强杀进程。

## 公司请先测试这五项

1. 只打开展示版：解释器、两类历史目录、参考文件、实时目录和分红均指向公司原路径；不需要 Excel/开发版，没有模态向导。
2. 有数据先显示，快检不阻塞主窗口；在已有 DDB 网络上自动认证、增量补库、校验和发布。缺 SDK、凭据不可解密、认证失败、网络不可达分别显示原因。未知/未深核不报完整。
3. 手动准备好实时网络，有限验证后确认 **持续采集正在运行、有效数据序号递增、源时推进、计算完成、页面已应用版本**。在有效交易时段连续观察 10–15 分钟。09:29（含）至15:01（不含）的既有交易日门控、逐行源时/质量、缺腿与同步规则保留。休市只能验收可用性和正确状态。
4. 测试概览/对应指数、期现/跨期/跨品种现有指标，切换合约、参数、输入 X；打开详情图像和解释/公式。切换后旧任务不覆盖新选择；计算慢时保留明确标注的上一结果，队列最多一个执行和一个最新待处理请求。
5. 断网再恢复、取消/只读、手动重试和关闭重开。关闭会等待本轮采集和历史写入正常结束；不误停其他用户任务。两个 App 可读同一库，但互斥锁只允许一个网络写入者；另一窗口明确等待并读取缓存。

## 有时间上限的诊断

窗口的“导出诊断”保存到该实例 `dashboard/runtime/app_sessions/<运行号>/report-*.json`，路径直接显示在窗口。报告包含源时/接收时间、持久化序号、缓存读取、计算开始结束、页面应用时间、队列和失败阶段，不含密码。

需要观察一段时间时，在 Git 根目录运行（15 秒自动退出）：

```powershell
& 'D:\conda\envs\swhy_delta1\python.exe' -B -X utf8 -m dashboard.app_diagnostics --seconds 15 --output .\dashboard\runtime\company_app_15s.json
```

盘中连续观察用 `--seconds 900`，最大15分钟，每3秒采样；不会发网络请求、打开窗口或操作进程。先保持 App 正常运行。比较 `collection.data_sequence` 与 `applied.realtime_sequence`，再看 `source_times`、`cache_read`、`calculation_seconds`、`ui_applied_at`，可以区分源端陈旧、请求失败、历史占用、读错目录、计算耗时和界面回填。序号递增并不等于源行情新鲜，源日期仍按原接收日推定，质量限制继续生效。

当前状态：**待公司实测**。请先回传主要功能和持续更新反馈；等待期间只修运行/更新问题。指标重构须同时满足公司反馈、你明确继续、最新指标 doc 到位；美术细化也留到公司主要功能实测之后。
