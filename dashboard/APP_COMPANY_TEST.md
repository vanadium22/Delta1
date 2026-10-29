# 公司本轮完整复测命令（2026-10-29）

本轮从75d9da0接续：下午包仅3份JSON，缺Overview/同运行关闭证据，尚不能确认新关闭耗时与现场年化输入。新增OutputDirectory直接保存本轮诊断，统一安全打包。此前Y盘10月27日表已成功读取/导入；20日分位16档完整，60日仍缺历史D。截图确认收盘折溢价已显示，盘中IOPV/净申购/申赎仍缺可靠定义；公司关闭耗时约1–2分钟待复测。本页是完整命令入口。公司Git根为 `D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard`，LocalRoot为其下 `dashboard/localsetting/app`。先正常关闭旧看板并等后台退出，保留Wind终端登录；用平时能打开Y:的同一Windows用户，在同一个PowerShell窗口按顺序执行。

确认公盘为 `Y:\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026`。本次公司drive_y.json记录DisplayRoot为 `\\192.168.91.230\FTPServer`，默认仍用Y路径，不猜拼IP地址、不重新映射。2026是年份目录，匹配 `指数基差情况_*.xlsx`，业务日以Sheet1!B1为准。

本次已回传过ZIP的公司用户，只需执行第1、4、5节；默认Runtime模式只要求版本/映射和开窗、关闭后两次Overview。第2、3节保留为按需数据排查，完整源复测时把下方deltaReturnMode改成full。

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

新D不回写过去。当前Local是当前业务时点D；非交易界面可能用昨日价格参考，须同时看Overview的pricing_day和D来源。公盘缺旧日时如实缺项，不拿今日单表或DDB重下价格掩盖。

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

这些均只读，不发布正式资料、不订阅、不改VPN。需要固定同一已完成交易日时，只对显式Wind阶段加 `-WindDay '2026-10-28'`，日期必须是实际已完成交易日；默认日期规则不改。

ETF能力测试总预算90秒，close_nav查看同日有效配对数；IOPV/净申赎/PCF返回mapping_required表示缺已核验字段/单位/带日定义，不等于本次接口失败或已取得数据。可选字段文件的真实参数与契约见 [DATA_CAPABILITIES](docs/DATA_CAPABILITIES.md)，不猜字段，不提交本地字段文件。本机缺WindPy不能推断公司缺WindPy。

## 4. 正常页面运行与开窗取样

```powershell
& "$env:WINDIR\System32\wscript.exe" '.\dashboard\start_presentation.vbs' --theme public --local-root $deltaLocalRoot
```

保持看板打开10–15分钟，实时VPN仍手动。**正常任务才会发布行业/ETF资料**；需要立即复核时，在“数据更新/设置”点一次“DDB一键补齐”：先复核Wind资料，再按实际缺口补概览日线，本地标准历史优先复用，等待结束，勿反复点击。缺项资料有每日有界修复，成分行情约60秒一轮。

检查20卡/16期货20与60分位、逐卡较昨日变化、行业覆盖/缺项、ETF同日收盘溢价、午休/盘前盘后参考及切页/滚动；可选验证行情分析查询、取消和CSV。研究32项/A02继续暂停。然后**保持窗口开着**，回到同一PowerShell执行：

```powershell
if ($deltaReturnMode -eq 'full') { ./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -OutputDirectory $deltaReport -WindStage Nav -NoPause }
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -OutputDirectory $deltaReport -Overview -NoPause
```

年化不一致时，把鼠标放在期货卡年化值上，查看F（期货）、S（指数）、D（分红点）、T（自然日）、定价日及D业务日；与Excel同一时点和实际合约比较。Excel文件名/B1/RTD价格变化不证明G列分红同步变化。Overview的data_gaps.page_calculation_preview.futures保留上述输入、两腿源时、到期日与D文件SHA；它是只读计算预览，不证明运行中页面已应用。不为对账自动导入另一份Excel覆盖Y源。

默认Overview离线，不启动采集或任何接口。Nav需要正常任务已发布ETF排名；尚未发布时失败也回传，不能用只读ETFs成功冒充生产发布。历史closing/stopped记录不能单独证明采样时当前窗口状态。

正常关闭看板，观察左上“正在安全关闭”的等待阶段、成分归档进度和秒数，等窗口自行退出；不强杀、不删锁。关闭后在同一PowerShell再运行一次：

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

本轮本地210项受影响测试通过（51.206秒，ResourceWarning作为错误，无跳过）；两份Excel共32行与当前计算函数一致，但15个合约D和其他输入不同，现场仍需同输入核验。前序1800标的隔离归档从8.884秒降至2.489秒，仅代表本机合成数据，不承诺公司相同耗时。Y读取/导入和收盘折溢价已由本次公司报告/截图确认；60日历史D、完整行业贡献、盘中IOPV/净申购/PCF和新关闭耗时仍有待办，缺定义不能猜填。此前55及229/62/272项属于历史批次。
