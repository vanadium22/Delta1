# 公司完整复测命令（2026-11-11）

## 2026-11-12 四品种期限结构复测

2026-11-12四品种期限结构坐标续改，统一codex/company-apps，实施基线2acf89c，运行版本以Git HEAD/远端为准。IF/IH/IC/IM的概览和股指期货详情均共用同合约、同到期日的缺项缓存回退；旧点标沿用及源时，T<5、换档或到期修订不错误沿用。每个品种每天首次有可用点时纵轴设为最小年化减2至最大年化加2（百分点），数据在范围内波动不缩放；越界时仅向外扩展被突破的一端，后来首次出现的新档补足2个百分点余量，次日重新初始化。横轴使用已知合约期限，当日不收缩；概览与详情共用各品种范围。范围在本次看板运行期间保存，重启按当时可用点重新初始化。

正常关闭并等待旧看板排空后，在公司原Git根更新并重开：

```bat
cd /d D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard
git pull --ff-only
```

检查IF/IH/IC/IM概览及股指期货详情，暂缺档是否保留同合约真实旧点和源时；四个品种分别查看年化纵轴区间，通常小幅波动保持、越界后扩展，次日重置。无历史缓存或T<5允许缺点；勿将缓存当实时。

543项完整回归通过，136.377秒（含加载），无跳过，ResourceWarning作为错误。 前次公司安全包运行a628472，同次关闭7.247秒、DDB复用隧道并认证；本轮无新的公司反馈。公司实盘四品种缓存回退、坐标行为与UNC直接访问仍需现场验证。

用户暂不制作分发压缩包，独立Python运行时、离线依赖、干净数据分发清单及新电脑验收继续留待后续。

原数据、配置、凭据、Excel、其他worktree、四份受保护提示词及APP_RELEASE.backtest原块保留；逐日D、简单年化、连续四档固定20/60保持，历史缺D暂0只派生、当前D不补0、冲突不填；32项/A02继续暂停。Overview默认离线，DDB不暂停，实时VPN手动；不强杀写入者、删锁、重映射Y、reset/clean、全量stage或强推。

以下前序记录与本轮结果不一致时，以本轮结果为准。

## 2026-11-12 期限结构与同事配置复测

2026-11-12期限结构与同事配置续改，统一codex/company-apps，实施基线da2aca5，运行版本以Git HEAD/远端为准。概览及股指期货页年化曲线共用每档回退：当前有效优先，缺项沿用同实际合约、同到期日的完整F/S/D/T，空心点及“沿用”、混合时点和原源时可见；每个期现仍须3秒配对，换档/到期修订及T<5不错误沿用。无真实历史值不伪造。

新用户可在数据更新/设置填写DDB和数据VPN账号；VPN需核验HTTPS网关及证书SHA256指纹。用户名和密码按当前Windows用户DPAPI保存在新版本本机文件，旧文件保留，界面不回显密码；保存凭据不主动暂停DDB。首次配置默认使用本看板本地账户文件，不自动发现其他应用账户；可达时继续复用已有数据隧道，实时VPN仍手动。

常用入口的Python环境设置或看板设置可选择解释器、检查要求的包和版本，并将完整依赖安装到看板专用隔离目录；优先使用随包wheelhouse，否则用户点击时使用pip配置源。校验成功才切换隔离目录，原Python包不修改；不同Wind/历史解释器不继承不兼容的本看板二进制依赖。启动器支持runtime/python/python.exe，且支持选择外部Python；Wind终端和VPN客户端仍须本机具备。

公盘默认 `\\192.168.91.230\FTPServer\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026`，由公司安全包已记录的Y映射根推导；直接UNC访问尚待公司验证。旧内置Y和旧UNC仅运行时转换，用户自定义和显式空白不变；新安全反馈记录share_source.json，旧drive_y.json仍可兼容读取，不强制映射盘符。

正常关闭并等待旧看板排空，在公司原Git根更新后重开：

```bat
cd /d D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard
git pull --ff-only
```

上证50两处期限结构应在有同合约真实缓存时保留暂缺点，查看“沿用”和原源时，恢复后使用新点。数据更新/设置可填写本机DDB、数据VPN，也可从常用入口打开Python环境设置。需要正式取证时可按后续旧流程运行安全复测；直接UNC访问与公司实盘显示仍待现场核验。

用户暂不打包：本轮未制作或发送分发ZIP，也未制作完成可搬运Python运行时或完整离线wheelhouse。后续打包需准备适用于同事机器的独立Python和依赖、经允许的数据与概览缓存，使用白名单并排除个人配置、凭据、Git历史、运行日志及备份；在干净Windows目录解压、断网启动并验证后，才可称解压即用。现有数据包按根目录定位，迁移后仅重定位其自身历史路径和看板生成的本地账户引用，不覆盖用户自定义路径。

原数据、配置、凭据、Excel、其他worktree、四份受保护提示词及APP_RELEASE.backtest原块保留；逐日D、简单年化、连续四档固定20/60保持，历史缺D暂0只派生、当前D不补0、冲突不填；32项/A02继续暂停。Overview默认离线，DDB不暂停，实时VPN手动；不强杀写入者、删锁、重映射Y、reset/clean、全量stage或强推。

以下前序记录与本轮结果不一致时，以本轮结果为准。

## 2026-11-12 行业变化复测

2026-11-12行业变化补全，统一codex/company-apps，实施基线a628472，最终运行版本以Git HEAD及远端为准。完整同口径历史比较优先；历史不全时按成分代码及真实权重日期配对，或在行情样本覆盖更高时按现有权重和有效成分涨跌估算。标题明确“部分成分”或“涨跌估算”，显示样本数、基准日期、缓存状态和百分点；缺项不补零、未知行业保留“待分类”。无可信权重或行情时仍显示真实缺项原因；公司新图效果待更新后验收。

本包归档读取23份，IC/IM各22组中17组重复、5组上期权重不完整或不可比，是旧变化图为空的直接原因；当前权重日期10-30，500只中49只、1000只中148只缺行业分类，二者属于另行统计的分类缺项。

公司安全包20261112_111531_749_safe_113124_158_68fd3bf7.zip，130457字节，SHA256 1e80ae4ff4d06748b8688e90c9bfef746296063321ec7a7e2da08f6cfadd101a，运行a628472；9份JSON、CRC正常、Complete=true、MissingReports=[]。同一515050c运行正常关闭7.247秒、waiting=[]，成分sqlite_committed。两次Overview及preflight退出0、stderr为空。

IM02同一选择在11:30:00.911、11:30:30.922、11:31:00.911实际绘图，相隔30.011秒、29.989秒。第一帧为11-12 11:29:56盘中行情，年化Z约0.0694、分位45%；后两帧为11-11收盘参考，年化Z约0.8326、分位75%；变动跨午休定价模式，不能据此宣称连续多个盘中tick均改变Z/分位，分位也不保证每个tick都变。

正常关闭旧看板等待排空，在公司原Git根执行：

```bat
cd /d D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard
git pull --ff-only && call dashboard\company_retest.cmd -SampleSeconds 900
```

进入指数页检查中证500/1000行业变化图及其样本数、基准日期，鼠标提示查看方法、范围和截止时间；估算应按估算理解，未覆盖股票不会虚构。数据输入完全缺失仍可能留空。用户可按实际需要运行取证并正常关闭。

原数据、配置、凭据、Excel、其他worktree、四份受保护提示词及APP_RELEASE.backtest原块保留；逐日D、简单年化、连续四档固定20/60规则保持，32项/A02继续暂停；默认Overview离线、DDB不暂停、实时VPN手动，不强杀写入者、删锁、重映射Y、reset/clean、全量stage或强推。

以下前序记录与本次结果不一致时，以本次记录为准。

## 2026-11-12 当前版本复测

2026-11-12公司复测续改，统一codex/company-apps，实施基线da50685，最终运行版本以Git HEAD/远端为准。概览将每个指数、四个期货卡及该品种期限/成交/持仓图合为一行，1080p/125%中比例无需滚动；小窗口可滚动以保持可读。ETF总览增加蓝色表头、交替底色、涨跌/折溢价颜色并放大字号；指标图最新点加大。行业变化缺项显示可比失败原因，并在安全报告中保留每品种判断摘要；不把缺失权重伪造为零。

公司安全包20261112_100603_500_safe_103108_772_2f9c3359.zip，121515字节，SHA256 faa33f5818c8f3fbfabeeabb6a76cc0197ddbf2061d7d2ad0bcf2486fcbdcc6f，运行da50685；9份JSON/CRC正常、Complete=true/MissingReports=[]，同一f12c8a运行开窗、正常关闭3.355秒、waiting=[]，成分sqlite_committed。两次Overview与preflight均退出0、stderr为空。

包内IC/IM当前权重均存在、权重日期10-30，成分中分别49/148只缺行业分类；安全包未记录上次可比权重决策或归档内容，不能证明这两项缺分类就是图不显示的原因。新版本在运行报告与离线预览中记录比较状态、当前/前次日期、来源口径、归档扫描/不兼容计数及未分类数；仅对同口径可比快照计算，保留“待分类”，无可比数据留空。

正常关闭旧看板等排空，在公司原Git根执行：

```bat
cd /d D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard
git pull --ff-only && call dashboard\company_retest.cmd -SampleSeconds 900
```

检查1080p/125%中比例概览四品种卡和图同屏，ETF表的颜色和可读性，指标当前点；指数页查看500/1000的行业变化及明确缺项原因。开窗取证前，在指标分析保持同一品种/档位至少65秒，再按脚本保存开窗Overview。核对同一app_reports记录的indicator_draw.timer_draws中相邻真实绘图时间、各自源时/数值/Z/分位，区分采集未变化和绘图未执行。正常关闭、等待排空后再取Overview，回传最后_safe_*.zip。同一记录的index_industry_changes给出每品种分类/归档可比原因；离线计算预览不冒充UI实际状态。

DDB不暂停，原凭据和192.168.198.77:8904沿用，可达时复用已有jc数据隧道；实时VPN手动。保留原数据、配置、凭据、Excel、其他worktree、四份受保护提示词、七份唯一归档及APP_RELEASE.backtest原块；逐日实际D、简单年化、连续四档固定20/60保持，历史缺D暂0只派生、当前D不补0、冲突不填；32项/A02继续暂停。Overview默认离线，不强杀写入者、删锁、重映射Y、reset/clean、全量stage或强推。

## 以下为前序详细流程

## 2026-11-12 当前版本复测

2026-11-12，统一分支codex/company-apps，实施基线95869c2，最终运行版本以Git HEAD/远端为准。指标页数值按原行情计算更新，图像在页面激活期间每30秒重画并标图像更新时间；缺项显示原因。概览突出00–03，去掉概览上的较昨基差变化；20/60分位并列同窗均值/中位数及日期，越接近两端越高亮；概览新增四品种期限/成交/持仓，指数页新增行业权重变化，ETF页新增全部现有订阅的总览表。

新公司包20261111_154729_881_safe_160539_083_91d394e8.zip，8886字节，SHA256 cbb1e517a16a39a252a69690bfe0ef4f4b522dcf456df8f1f84c2834fb38c262；95869c2、7份JSON且CRC正常，但Complete=false，开窗与关闭后overview.json均缺失，缺少同次安全排空证据。两次诊断均报System.Management.Automation.RemoteException/NativeCommandError，preflight退出0；没有原始stderr，不能据此确定Z/分位为何为空、DDB状态或同次关闭完成。

更新前正常关闭旧看板等排空，在原Git根运行：

```bat
cd /d D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard
git pull --ff-only && call dashboard\company_retest.cmd -SampleSeconds 900
```

保持看板打开，盘中确认指标当前值/Z/分位随有效行情变化；连续观察至少30秒，核对图像更新时间及最新点。核对概览00–03卡片20/60窗口日期、avg/中位数及两端分位高亮，向下查看四品种期限、成交、持仓及持仓日期；指数页看权重与变化的日期/分类，ETF总览查看已有全部ETF行。缺数据保留原因，不要求伪造数值。需要时仅点一次“补齐所选窗口”，等完成。开窗取证前留在指标分析页且等计算完成，取开窗Overview后正常关闭并等待排空，再取关闭后Overview，回传最后_safe_*.zip；检查Complete、app_reports.matching_profile[].indicator_analysis、数据源时和诊断overview_stderr分类。DDB继续自动，jc隧道可达则复用，实时VPN手动。若还要专门核验11-10可加-ExpectedCloseDay 2026-11-10，但不能以该日期代替最新真实完成日。

## 以下为前序详细流程和历史记录

本次在39760f0后正式实现“指标分析”，最终运行提交见Git HEAD；469项独立完整回归通过，105.841秒（含加载），无跳过，ResourceWarning作为错误；原438项全部重跑，新增31项指标页回归。 b7d5d55新公司包已确认11-10四指数/16期货昨收及16档20/60恢复、新端点DDB认证/query_partial/existing_tunnel、同次关闭2.731秒。仍缺16期货OI与12 ETF收盘，不当业务全通过。

## 本轮重点

1. 正常关闭旧看板等排空，原Git根更新后执行下方一键复测。默认入口、LocalRoot、依赖、配置及账号密码继续复用；DDB不暂停、可达时复用既有jc数据隧道，实时VPN手动。
2. 新同级“指标分析”：切换IF/IH/IC/IM；基差默认00，可选01/02/03，只影响左两图。右两图始终03−02、02−01。看叠加图统计去分红/绝对切换，四图/基差/跨期查看切换。
3. t_w默认90自然日、10–365可调；t_z默认min(20,floor(t_w/2))交易日、2–120可调。关闭自动后手动t_z不随t_w改变。确认四项统计统一t_z、均值/中位数水平虚线横跨t_w。悬浮查看具体合约/F/S/D/T、缺项、临期排除、历史D暂0和HTTP日期推定，不把断口补成连续线。
4. 需要历史时在指标页点一次“补齐所选窗口”，等原Wind→本地→HTTP最新昨收→DDB剩余日线流程结束；不反复点击、不恢复研究分钟/32项/A02。真实缺价/映射/冲突留空，当前D不补0；非连续时段看标明日期的完成收盘参考，不拿昨天价冒充今日。
5. 1080p/125%最大化检查四图同屏；窄窗口单列/统计移到图下并可滚动。最终保持指标页打开，等一轮计算后按脚本回车保存开窗Overview；正常关闭等排空，再回车保存关闭后Overview并回传最后_safe_*.zip。app_reports.matching_profile[].indicator_analysis有本次应用选择、当前值/统计/样本缺项白名单，未在该页时可为空；不以离线计算预览冒充屏幕验收。
6. 保留11-10专项核验。若测试时已进入后续已完成日，另外核验正确最新完成日，不把11-10缓存当更晚收盘。15:10前11-11尚未纳入完成日；之后HTTP yesterdayClosePrice仍是11-10，只能由真实11-11收盘来源补11-11。期货OI/ETF收盘继续按真实缺口判断。

## 0. 推荐：一键Runtime复测

先正常关闭旧看板，在CMD执行以下更新取得新脚本；以后可直接双击dashboard/company_retest.cmd。

```bat
cd /d D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard
git pull --ff-only && call dashboard\company_retest.cmd -SampleSeconds 900 -ExpectedCloseDay 2026-11-10
```

脚本检查codex/company-apps并ff-only更新，记录新HEAD/本轮时间/Y映射，打开正常看板，本次命令保持15分钟（默认不传参数为10分钟）供约5分钟成分轮询和Wind规模历史更新。按提示保持开窗保存Overview，再正常关闭、等排空、关闭后Overview及安全打包。只回传最后打印的ZIP。脚本不操作VPN、不重新映射Y、不强杀；无本轮开窗或最终同运行安全关闭时仍生成明确缺项包。Git错误保留现场，不reset/clean。

ExpectedCloseDay仅指定本轮重点核验日，不修改日历或伪造数据日期。安全包完整不等于价格/分位已全部补齐，仍需核对Overview里的实际缺项与来源。

非默认LocalRoot可在PowerShell调用：

```powershell
./dashboard/company_retest.cmd -LocalRoot 'D:/实际配置目录' -SampleSeconds 600
```

重点看：1080p最大化后“中”全卡可见且卡内数字更大，“大”可滚动，“小”更紧凑；在概览及指数页分别点击四个指数，查看行业覆盖、篮子涨跌条及贡献；ETF数字/带日收盘折溢价、两个规模饼图（同指数前三ETF+其它；四实际期货名义本金），留意日期和已知n/4标记；期货加粗横条文字在色块内。刷新暂缺配对时应保留上次完整基差/年化/分位并标沿用源时，现价可独立更新。

以下是完整手动和按需分红/行业ETF排查。一键已完成时不重复执行。Runtime只需第1、4、5节，full另做第2、3节。正确Y源为Y:\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026，业务日B1；现场DisplayRoot为\\192.168.91.230\FTPServer，仅记录，不猜拼/重映射。命令不改原配置/凭据/Excel。

## 1. 更新与本轮输出

```powershell
Set-Location -LiteralPath 'D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard'
git status --short --branch
if ((git branch --show-current).Trim() -ne 'codex/company-apps') { throw '当前不是codex/company-apps；保留现场，先核对分支。' }
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw 'Git更新未完成；保留现场并回传终端提示。' }
git log -1 --oneline

$deltaLocalRoot = Join-Path (Get-Location) 'dashboard/localsetting/app'
if (-not (Test-Path -LiteralPath (Join-Path $deltaLocalRoot 'native.json'))) { throw '公司LocalRoot/native.json不存在，先核对实际配置位置。' }
$deltaSource = 'Y:\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026'
$deltaReturnMode = 'runtime'
$deltaTestStarted = Get-Date
$deltaReport = Join-Path (Get-Location) ('dashboard/runtime/company_retest/' + $deltaTestStarted.ToString('yyyyMMdd_HHmmss_fff'))
New-Item -ItemType Directory -Path $deltaReport -ErrorAction Stop | Out-Null
[pscustomobject]@{ LocalRoot=$deltaLocalRoot; Branch=(git branch --show-current).Trim(); Commit=(git rev-parse HEAD).Trim(); Status=@(git status --short --branch); StartedAt=$deltaTestStarted.ToString('o') } |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $deltaReport 'git.json') -Encoding UTF8
$deltaYDrive = Get-PSDrive -Name Y -ErrorAction SilentlyContinue
[pscustomobject]@{ Mapped=[bool]$deltaYDrive; Name=$deltaYDrive.Name; Root=$deltaYDrive.Root; DisplayRoot=$deltaYDrive.DisplayRoot; ExpectedServer='192.168.91.230' } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $deltaReport 'drive_y.json') -Encoding UTF8
Write-Host ('本轮输出目录：' + $deltaReport)
```

`drive_y.json`仅记录映射元数据。DisplayRoot为空时可额外执行 `net use Y:` 查看Remote名称；此命令不重新映射。Git有冲突/错误时保留现场，不reset/clean。不要将native.json或命令的原始异常日志放进回传目录。

## 2. 按需复核分红导入与实际来源

```powershell
./dashboard/diagnose_dividends.cmd -LocalRoot $deltaLocalRoot -Stage Local -Output (Join-Path $deltaReport 'dividend_before.json') -NoPause
./dashboard/diagnose_dividends.cmd -LocalRoot $deltaLocalRoot -Stage Share -SourceDirectory $deltaSource -Output (Join-Path $deltaReport 'dividend_share.json') -NoPause
./dashboard/diagnose_dividends.cmd -LocalRoot $deltaLocalRoot -Stage Import -SourceDirectory $deltaSource -Output (Join-Path $deltaReport 'dividend_import.json') -NoPause
./dashboard/diagnose_dividends.cmd -LocalRoot $deltaLocalRoot -Stage Local -Output (Join-Path $deltaReport 'dividend_after.json') -NoPause

$deltaDividend = Get-Content -LiteralPath (Join-Path $deltaReport 'dividend_after.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$deltaDividend.diagnostic_profile | Format-List
$deltaDividend.audit | Select-Object record_count,file_versions,oldest_business_day,latest_business_day,history_dividends_complete | Format-List
$deltaDividend.audit.sources | Select-Object configured_share_directory,share_directory,store_directory,configured_file | Format-List
$deltaDividend.audit.current_dividends.'IF00.CFE' | Format-List contract_id,points,source_business_date,effective_from,file_sha256,inherited_from,reason
```

Local离线；Share有界只读检查Y盘并临时验证，不发布；Import追加到新库。`SourceDirectory`仅覆盖这次Share/Import读取，不保存配置。`diagnostic_profile`标识实际native文件位置/SHA；`sources.configured_share_directory`是原配置值，`share_directory`是有效源，二者可不同。

退出2/ok=false可能仅是历史D不完整，继续后续诊断并回传。分开看 `sync.status/inserted/business_dates`、`matched_names/source_directories`、`audit.latest_business_day/history_dividends_complete` 和16项 `current_dividends`，不能把历史未齐解释为本次文件未读取。`matched_names`是年份目录文件名样本，实际日期看B1解析结果；窗口外业务日见 `outside_range_files`，文件名旧或超出窗口不决定业务日。

历史缺D暂0仅用于分位计算，补零信息留在悬浮/诊断；Local仍审计真实D覆盖，不会因估算可算而把history_dividends_complete改为true。补入历史旧日表会替换该日占位，新D不回写过去。当前Local是当前业务时点D；非交易界面可能用昨日价格参考，须同时看Overview的pricing_day和D来源。公盘缺旧日时如实缺项，不拿今日单表或DDB重下价格掩盖。

可选：若另有已下载的本地Excel，在打开看板前执行，**仅修改第一行路径**：

```powershell
$deltaDownloadedFile = 'T:\inani\下载\AI\分红\指数基差情况_2026-10-27.xlsx'
./dashboard/diagnose_dividends.cmd -LocalRoot $deltaLocalRoot -Stage Import -InputFile $deltaDownloadedFile -Output (Join-Path $deltaReport 'dividend_downloaded.json') -NoPause
./dashboard/diagnose_dividends.cmd -LocalRoot $deltaLocalRoot -Stage Local -Output (Join-Path $deltaReport 'dividend_after.json') -NoPause
```

`InputFile`只允许Import，与SourceDirectory互斥；跳过公盘同步，追加到相同新库，原件/配置不改。`file_import.status=imported/unchanged`、business_dates和SHA证明指定文件已读取或同内容已存在。下载目录不会自动扫描。默认自动主源为Y盘；已有其他自定义目录保留，若要持续改源，需在设置中核对并手动保存，SourceDirectory不会替你持久化。

## 3. 按需复核行业与ETF只读阶段

```powershell
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -OutputDirectory $deltaReport -WindStage Connect -NoPause
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -OutputDirectory $deltaReport -WindStage Indices -NoPause
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -OutputDirectory $deltaReport -WindStage ETFs -NoPause
./dashboard/diagnose_data_capabilities.cmd -LocalRoot $deltaLocalRoot -Stage Local -Output (Join-Path $deltaReport 'etf_local.json') -NoPause
./dashboard/diagnose_data_capabilities.cmd -LocalRoot $deltaLocalRoot -Stage ETF -Output (Join-Path $deltaReport 'etf_capabilities.json') -NoPause
```

这些均只读，不发布正式资料、不订阅、不改VPN。需要固定同一已完成交易日时，只对显式Wind阶段加 `-WindDay '2026-11-09'`，日期必须是实际已完成交易日；默认日期规则不改。

ETF能力测试总预算90秒，close_nav查看同日有效配对数；IOPV/净申赎/PCF返回mapping_required表示缺已核验字段/单位/带日定义，不等于本次接口失败或已取得数据。可选字段文件的真实参数与契约见 [DATA_CAPABILITIES](docs/DATA_CAPABILITIES.md)，不猜字段，不提交本地字段文件。本机缺WindPy不能推断公司缺WindPy。

## 4. 正常页面运行与开窗取样

```powershell
& "$env:WINDIR\System32\wscript.exe" '.\dashboard\start_presentation.vbs' --theme public --local-root $deltaLocalRoot
```

保持看板打开10–15分钟，实时VPN仍手动。**正常任务才会发布行业/ETF资料**；需要立即复核时，在“数据更新/设置”点一次“一键补齐收盘”：先复核Wind资料，再本地标准历史/经日期核验的HTTP昨收，重新计划后才用DDB补历史缺口，等待结束，勿反复点击。缺项资料有每日有界修复，成分独立默认300只/15秒、仍约5分钟一轮，缺项下轮优先，大批回包不足70%时下一轮降100，每批保存；主报价仍3秒，个股昨收用HTTP，不每轮DDB取全体成分。App日常不再关闭时逐股Parquet导出。

检查概览顶部“最新分红表”日期、20卡/16期货20与60分位、逐卡较昨日变化、行业覆盖/缺项、ETF无盘中值时主位的带日收盘溢价、加重的规模/占比/买卖价差，以及ETF/期货规模双饼图、四指数真实点击、1080p中比例全卡/卡内较大数字和期货粗条内嵌标签、午休/盘前盘后参考及切页/滚动；可选验证行情分析查询、取消和CSV。研究32项/A02继续暂停。然后**保持窗口开着**，回到同一PowerShell执行：

```powershell
if ($deltaReturnMode -eq 'full') { ./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -OutputDirectory $deltaReport -WindStage Nav -NoPause }
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -OutputDirectory $deltaReport -Overview -NoPause
```

期货卡新增D来源日期；数值旁不放“估”，窗口内历史缺D暂0的天数在悬浮查看，Overview另列zero_dividend_dates/zero_dividend_assumptions。

年化不一致时，把鼠标放在期货卡年化值上，查看F（期货）、S（指数）、D（分红点）、T（自然日）、定价日及D业务日；与Excel同一时点和实际合约比较。Excel文件名/B1/RTD价格变化不证明G列分红同步变化。Overview的data_gaps.page_calculation_preview.futures保留上述输入、两腿源时、到期日与D文件SHA；它是只读计算预览，不证明运行中页面已应用。不为对账自动导入另一份Excel覆盖Y源。

默认Overview离线，不启动采集或任何接口。Nav需要正常任务已发布ETF排名，同时有界取近三个月规模，aum_history单列观测数/首尾日期，缺值不前填。尚未发布时失败也回传，不能用只读ETFs成功冒充生产发布。历史closing/stopped记录不能单独证明采样时当前窗口状态。

正常关闭看板，观察左上“正在安全关闭”的等待阶段、提交/排空进度和秒数，等窗口自行退出；不强杀、不删锁。关闭后在同一PowerShell再运行一次：

```powershell
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -OutputDirectory $deltaReport -Overview -NoPause
```

这次离线Overview读取最终closed/shutdown.complete/elapsed_seconds和成分归档状态；它不启动App或网络。新参数OutputDirectory使两次Overview直接保留在deltaReport下各自的diagnosis子目录，分别说明开窗行情/页面和关闭后排空，不能用关闭后的缓存时间判断开窗时网络中断。

## 5. 仅收白名单JSON并打包

以下命令调用仓库内的打包脚本，只复制固定白名单JSON到新建安全目录，验证JSON后压缩并核验ZIP扩展名。native.json、原始异常日志、SQLite、Excel及整个业务目录不会被复制；不要直接压缩LocalRoot或整个runtime。

```powershell
./dashboard/collect_company_return.cmd -ReportDirectory $deltaReport -LocalRoot $deltaLocalRoot -RunMode $deltaReturnMode
```

回传最后打印的ZIP：Runtime模式包含git/映射、开窗与关闭后各自diagnosis/preflight/overview及return_manifest；Full模式另含分红、ETF能力、各Wind阶段结果。脚本核对Runtime两次报告属于同一看板运行记录且最终shutdown.complete，return_manifest.Complete与MissingReports明确区分完整和缺项；脚本同时从旧runtime按diagnosis.at恢复本轮报告，不依赖Windows文件夹CreationTime。缺失时仍可回传定位，不补造成功结果。

另用一句话注明测试时间、Overview取样时窗口是否开着、行业/ETF是否出现、正常关闭约几秒；页面异常可另附截图。正常关闭后等写入者排空，不强杀、不删锁。不要发送native.json、凭据、原始异常日志、SQLite或Excel。

## 自动复制与验收判断

默认自动缓存为 `<LocalRoot>/overview_dividends`，实际位置看audit.sources.store_directory；raw按业务日/SHA归档，records.sqlite保存版本，derived.sqlite保存计算缓存。09:00/15:30上海检查，成功时段不重复，失败有限退避；首次按20/60历史加缓冲窗口筛选B1，后续增量并保留旧记录。文件晚于成功检查产生时手动更新，或按实际产出时间调整设置，不持续轮询下载目录。

本轮[APP_VALIDATION](APP_VALIDATION.md)：469项独立完整回归通过，105.841秒（含加载），无跳过，ResourceWarning作为错误；原438项全部重跑，新增31项指标页回归。 最新已审b7d5d55公司包同次关闭2.731秒，11-10四指数/16期货昨收及全部原20/60分位恢复；新指标页仍待公司更新验收。

新启动器仍每次完整离线预检，成功后同Python解释器打开窗口。diagnosis.latest_launch增加startup_mode、preflight_seconds、process_started_at、app_entry_at；Overview.app_reports.matching_profile[].startup包含clock_scope、preflight_seconds、app_main_seconds、handover_seconds、window_shown_seconds、first_result_seconds。后两项分别为window.show返回和首轮结果，不代表实时行情首达；共享解释器时钟不包含外层VBS/PowerShell创建开销。按同一run_path比较，不混旧会话。本机空配置速度不替代公司完整数据量实测。

Overview的data_gaps.page_calculation_preview.market_sizes保留OI手数、价格、乘数、金额、日期/来源。已回传16档为11-09完成日线，IF/IH300、IC/IM200，已复算通过；不是11-10实时持仓。未齐只展示已知n/4，完整总额留空，不能以成交量/伪0代替。仅实际OI缺口才按原一键维护补齐，不需为复测重复下载全体成分/研究分钟。

默认Overview诊断仍不联网。正常App启用后台时，接入时段外会每约60秒获取一次有限HTTP快照并标非实时；--no-realtime或暂停不请求。Wind/Y/DDB参数、逐日D/连续20与60/简单年化保持，研究32/A02继续暂停。
