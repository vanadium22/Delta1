# 公司完整复测命令（2026-11-11）

本轮DDB新地址为192.168.198.77:8904，原账号密码/TLS沿用。更新页已改为滚动分组，并区分价格日、DDB目标和Y盘分红日。本机直连新地址3秒超时，未查询11-10；公司新连接和布局待现场核验。原公司Git根/LocalRoot/完整复测链保持。

## 本次更新后的简短核验

正常关闭旧看板并等待排空后，在公司原Git根执行git pull --ff-only，再通过原入口重开。进入“数据更新/设置”：

1. 确认DDB生效地址192.168.198.77、端口8904；新版App直接采用发布地址并沿用原凭据引用，无需重填账号密码。显式history_ddb_host/history_ddb_port优先；确需自定义时，使用“保存地址和端口”，只保存非秘密地址，不改原凭据文件。
2. 11月11日盘前目标收盘应为2026-11-10。价格数据日取卡片真实源时间；“最新分红表（Y盘）”即使仍11-06，也不能单凭它判断DDB断开。
3. 点一次“DDB一键补齐”并等待完成，查看上次DDB阶段/错误及价格日是否到11-10；未成功时保留旧缓存。设置页展开后用右侧滚动条访问全部字段，原账号/密码高级设置仍保留。
4. 默认Overview可离线回传data_gaps.ddb.connection、maintenance及app_reports.matching_profile[].history_update；connection只是配置，maintenance中的目标/阶段才是实际任务证据，旧目标不可混入本次。

下方原一键流程可自动完成安全ZIP。实时VPN仍手动，不强杀写入者或重新映射Y。

## 0. 推荐：一键Runtime复测

先正常关闭旧看板，在CMD执行以下更新取得新脚本；以后可直接双击dashboard/company_retest.cmd。

```bat
cd /d D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard
git pull --ff-only
call dashboard\company_retest.cmd
```

脚本检查codex/company-apps并ff-only更新，记录新HEAD/本轮时间/Y映射，打开正常看板，默认保持10分钟供约5分钟成分轮询和Wind规模历史更新。按提示保持开窗保存Overview，再正常关闭、等排空、关闭后Overview及安全打包。只回传最后打印的ZIP。脚本不操作VPN、不重新映射Y、不强杀；无本轮开窗或最终同运行安全关闭时仍生成明确缺项包。Git错误保留现场，不reset/clean。

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

保持看板打开10–15分钟，实时VPN仍手动。**正常任务才会发布行业/ETF资料**；需要立即复核时，在“数据更新/设置”点一次“DDB一键补齐”：先复核Wind资料，再按实际缺口补概览日线，本地标准历史优先复用，等待结束，勿反复点击。缺项资料有每日有界修复，成分独立默认300只/15秒、仍约5分钟一轮，缺项下轮优先，大批回包不足70%时下一轮降100，每批保存；主报价仍3秒，个股昨收用HTTP，不每轮DDB取全体成分。App日常不再关闭时逐股Parquet导出。

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

本轮[APP_VALIDATION](APP_VALIDATION.md)为388项回归通过，103.581秒，无跳过、ResourceWarning作为错误，含DDB端点/日期/凭据与滚动表单新增验证。公司最新b5746c7包同次安全关闭6.153秒；7.422和73.499秒为更早运行，不能混算。

新启动器仍每次完整离线预检，成功后同Python解释器打开窗口。diagnosis.latest_launch增加startup_mode、preflight_seconds、process_started_at、app_entry_at；Overview.app_reports.matching_profile[].startup包含clock_scope、preflight_seconds、app_main_seconds、handover_seconds、window_shown_seconds、first_result_seconds。后两项分别为window.show返回和首轮结果，不代表实时行情首达；共享解释器时钟不包含外层VBS/PowerShell创建开销。按同一run_path比较，不混旧会话。本机空配置速度不替代公司完整数据量实测。

Overview的data_gaps.page_calculation_preview.market_sizes保留OI手数、价格、乘数、金额、日期/来源。已回传16档为11-09完成日线，IF/IH300、IC/IM200，已复算通过；不是11-10实时持仓。未齐只展示已知n/4，完整总额留空，不能以成交量/伪0代替。仅实际OI缺口才按原一键维护补齐，不需为复测重复下载全体成分/研究分钟。

默认Overview诊断仍不联网。正常App启用后台时，接入时段外会每约60秒获取一次有限HTTP快照并标非实时；--no-realtime或暂停不请求。Wind/Y/DDB参数、逐日D/连续20与60/简单年化保持，研究32/A02继续暂停。
