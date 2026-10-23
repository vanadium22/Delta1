当前公司日常入口已改为展示版 App。11:07 两份回传报告已经确认指定孤立任务安全退出、活跃窗口保留、有限 HTTP 验证成功；不再把该次 PermissionError 当成未解决的 VPN 授权问题。持续采集当时未启动。新 App 的分阶段证据与有上限的15秒/15分钟观察命令见 [APP_COMPANY_TEST.md](APP_COMPANY_TEST.md)；下面是此前孤立任务恢复证据与命令，不需重复恢复已结束的运行。

# 历史扫描与公司实时连接诊断

2026-10-23：公司已确认占锁的是脱离原窗口运行的数字Excel后台：启动器和原Excel均不存在、心跳停在两天前，但后台仍在采集。新的验证被它的互斥锁拦截；这不能解释为行情接口拒绝访问。Excel与两版本地App共用安全诊断说明，数据和配置保留。

## 已确认的原因与安全恢复

旧数据服务只读取本次运行目录的停止文件。启动器意外退出时，清理代码可能没有执行，停止文件也没有生成，后台于是继续重算和采集。公司现场的旧窗口心跳停在10月21日13:41，但对应后台10月23日10:40仍在计算，源时已到10:39:43，且独占网络锁。源时说明近期存在行情数据更新，不保证全部20个代码或当前链路仍完整、新鲜；新实例需在收尾后验证。

新版启动器把自己的PID和精确创建时间交给本次数据服务。服务持有原进程的查询/等待句柄，观察真实进程退出，避免PID复用误判；不使用心跳超时判断存活，不会因为Excel编辑、计算慢或短时无响应就停止。启动器退出或本轮停止文件出现后，独立监视线程先通知采集停止，数据计算在可取消边界退出，采集完成清理后释放互斥锁。Windows依据见 [进程等待接口](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject) 和 [进程创建时间](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes)。不调用进程终止接口，不管理其他Excel窗口。无启动器参数的独立命令行保持原有显式停止方式。

`git pull` 不会重启正在运行的旧Python。新增 `python -m dashboard.numeric_recovery --output ...` 默认只检查原运行记录；显式加 `--stop-orphans` 才请求符合条件的旧任务自行退出。必须同时满足：运行号及目录合法、当前入口为数字Excel、进程实际feed/stop路径与该运行记录一致、原启动器PID及Excel PID均不存在、带时区心跳已过期至少120秒。写停止标记前重新查询并核对进程创建时间；任何必要信息缺失、查询权限失败、路径不符或原窗口仍存在均不处理。PID被其他进程复用导致存在时也保守保留。

只新建本轮目录的 `stop`，不改原run.json、feed、工作簿、行情库和配置，不删除writer.lock，不强杀任何进程、不弹窗、不切VPN。总计等待已请求任务自行退出最多30秒；没有观察到退出时返回非0，保留报告并停止后续命令。无有效运行记录的老任务不凭PID猜测收尾。报告的 `ok=true` 仅表示恢复步骤完成，不代表连接验证成功；仍可能有正常采集器持有网络锁。

公司在原仓库根目录整块执行；先保留已手工连接的实时行情VPN，不使用任何自动VPN参数：

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $env:GIT_TERMINAL_PROMPT = '0'; $env:GCM_INTERACTIVE = 'Never'
    if ((git branch --show-current) -ne 'codex/company-apps') { throw '当前不是公司统一分支，请回传输出' }
    git pull --ff-only origin codex/company-apps
    if ($LASTEXITCODE -ne 0) { throw '更新失败，停止' }
    $py = 'D:\conda\envs\swhy_delta1\python.exe'
    $stamp = Get-Date -Format yyyyMMdd_HHmmss_fff
    $recovery = Join-Path $PWD ("dashboard\runtime\company_recovery_$stamp.json")
    & $py -B -X utf8 -m dashboard.numeric_recovery --stop-orphans --output $recovery
    if ($LASTEXITCODE -ne 0) { Write-Output $recovery; throw '收尾未完成，请回传该报告；不要强杀进程' }
    $connection = Join-Path $PWD ("dashboard\runtime\company_connection_$stamp.json")
    & $py -B -X utf8 -m dashboard.connection_check --all-profiles --connect --lock-owners --output $connection
    if ($LASTEXITCODE -ne 0) { Write-Output $connection; throw '诊断未完成，请回传输出和已有报告' }
    Get-Item -LiteralPath $recovery,$connection | Select-Object FullName,Length
}
```

把两个报告回传；如果新验证仍被正常采集器占锁，按其中的使用进程与原始行情时点判断，不停止正在使用的窗口。原Excel文件继续保留为已保存快照；重新启动原入口才能加载本次生命周期修复，程序不会自动打开产品。

## 已收到的公司证据与下一步

公司10:17报告中，历史任务09:20完成40次查询、补入4,820条，指数与期货共同发布到2026-10-22。其扫描编号等新字段为空，属于旧格式历史记录；保留完成/发布时间，但旧0缺口不能作为新版重扫结果。

`PermissionError` 发生在 `bars._writer_lock` 的 `msvcrt.locking(..., LK_NBLCK, 1)`，锁文件可打开写权限、读取首字节失败，指向已有进程持有字节锁。`http_attempted=false`，HTTP/DNS/TCP没有执行，当前不能判断公司VPN和接口是否正常。

随后返回的进程摘要包含跨日Python与两个Excel，但不能据此认定谁异常。上一条手动PowerShell匹配规则未兼容带引号的 `"-m" "dashboard.numeric_excel"`；数字Excel启动器实际会给每个参数加引号，因此“other Python”也可能是看板后台，不代表已确认与本项目无关。

在公司原Git根目录执行以下命令，保留当前相关进程与锁文件。这一步不请求行情、不开始采集或补历史，不需要切换VPN：

```powershell
git pull --ff-only origin codex/company-apps
if ($LASTEXITCODE -ne 0) { throw '更新失败，保留现场停止' }
$report = Join-Path $PWD ('dashboard\runtime\company_lock_' + (Get-Date -Format yyyyMMdd_HHmmss_fff) + '.json')
& 'D:\conda\envs\swhy_delta1\python.exe' -B -X utf8 -m dashboard.connection_check --all-profiles --lock-owners --output $report
$report
```

`--lock-owners` 不隐含 `--connect`。它通过Windows自带的 [Restart Manager资源查询接口](https://learn.microsoft.com/en-us/windows/win32/api/restartmanager/nf-restartmanager-rmgetlist) 取得各锁文件的使用进程PID与创建时间，再用本机CIM补充Python/Excel及相关PID的程序路径、父PID、创建时间、看板模块名。模块识别兼容带引号的参数；只额外保留数字Excel的feed/stop路径及全机PID存在性列表用于安全核对，完整命令行、其他参数、进程窗口标题和文档名不进入报告。查询只建立并结束自己的系统查询会话，不调用关闭/重启应用接口，不结束业务进程、不删锁文件、不弹窗或申请提权。

报告每份配置的 `network_lock.file_users_query` 与顶层 `processes` 可对应PID和 `started_filetime`；同时核对创建时间，避免PID被复用。`file_users` 是文件使用者候选，不直接证明谁持有哪一段字节锁；多个使用者、空结果、访问拒绝或进程已退出时，需结合本轮锁访问结果继续判断。`state=unavailable` 与 `missing` 不解释为“锁已释放”；API错误、CIM失败与超时分别保留，查询失败不会自动停止任务或尝试管理员权限。

原生查询在单独隐藏子进程内最多20秒，进程摘要最多12秒；超时仅清理本次诊断自己的子进程。普通历史/行情后台保持原状。当前若正常实时采集已经持锁，另一个验证任务被拦截是互斥行为，不能据此认定原采集器已断线。

## 扫描结果如何显示

每轮扫描都有独立编号。开始扫描后，当前缺口条数、待处理项数和旧任务明细立即失效，显示“缺口待核验”和已扫描/总组数。只有完成全量扫描、生成本轮计划后才显示实际缺口，合法的0仍显示0。

明细同时核对扫描编号、目标日期和数据版本，不能把上轮“0缺口”用于新目标。停止或失败发生在扫描完成前时，继续显示“扫描未完成”。既有缺口文件保留，但不当作本轮结果。最近发布/最近完整时间作为历史记录独立保留。

## 公司电脑执行

保持当前报错相关进程的状态，先执行诊断，避免停止进程后锁占用的证据消失。只需保持你已手动连接的实时行情 VPN；脚本不会切换、登录或退出 VPN，不启动 Excel/App，不补历史、不持续采集。

在公司原 Git 根目录的 PowerShell 执行：

```powershell
git pull --ff-only origin codex/company-apps
if ($LASTEXITCODE -ne 0) { throw '更新失败；保留现场停止' }
$report = Join-Path $PWD ('dashboard\runtime\company_connection_' + (Get-Date -Format yyyyMMdd_HHmmss_fff) + '.json')
& 'D:\conda\envs\swhy_delta1\python.exe' -B -X utf8 -m dashboard.connection_check --all-profiles --connect --output $report
$report
```

使用公司已有且已验证的解释器；无需安装包、激活环境或改永久变量。`--all-profiles` 只读取已存在的数字 Excel 配置与 App 配置，报告分别保留各自路径；不会创建或覆盖配置。如只查一个入口，可用 `--local-root .\dashboard\localsetting\numeric_excel` 或 `--local-root .\dashboard\localsetting` 替代 `--all-profiles`。

`--connect` 在行情接入时段内对每份现有配置执行一次有限验证，并检查DNS、最多两个地址的TCP端口和本机所选路由。所有网络检查遵守历史/实时互斥：锁未取得时跳过HTTP及DNS/TCP；时段外跳过网络。只做本地检查时省略 `--connect`。正常写出报告的退出码0表示“诊断执行完成”，不等于连接成功，请看各 `probe.ok` 和分阶段结果。

把生成的JSON发回用于继续定位。报告不含数据库/VPN凭据、HTTP头、行情正文、原始异常文本或局部变量；包含当前Python、配置/锁文件路径、异常调用位置、安全错误码、DNS地址和路由。不同诊断使用不同文件，已有报告不覆盖。

## 如何区分 PermissionError 与连接失败

| 字段/阶段 | 含义及下一步 |
|---|---|
| `reference_read` | 合约参考文件读取失败，尚未请求行情。检查报告中的实际文件路径与当前用户读取权限。 |
| `network_lock`，`http_attempted=false` | 在本机网络互斥锁处失败。结合异常 `filename`、`path`、调用行、`errno/winerror`，以及本地锁文件“读取字节/只打开写权限”结果区分占用、共享限制或ACL；不能直接认定VPN不通。 |
| `client_init` | 行情客户端初始化失败。若有文件路径，核对已有依赖或证书文件访问。 |
| `http_request`，`winerror=10013` | 已取得锁，套接字访问被系统拒绝。继续核对公司安全软件、应用网络权限与VPN策略；不是同一类文件锁错误。 |
| `http_request`，`status=timeout` | 接口超时。`transport_error` 可区别 `ConnectTimeout` 与 `ReadTimeout`；结合DNS、TCP和路由检查资源是否真正可达。 |
| `tls_error` | TLS证书校验失败；核对公司可信证书，保留校验，不关闭验证。 |
| `http_error` 和HTTP状态码 | 请求到达服务并收到了HTTP响应，按403/其他状态继续核对服务权限或网关。 |
| `response_validation` | 服务响应或代码/价格不完整。需要继续核对行情服务返回结构，当前报告不保存行情正文。 |
| `client_close` / `network_lock_release` | 请求后的清理阶段失败，不应误报为请求前的锁冲突。 |

Excel 启动验证的JSON仍在本轮 `runtime/numeric_live` 目录，错误提示显示该报告位置。两版 App 的共用向导将每次验证写入本地 `runtime/connection_checks/connection-*.json`，错误提示可直接看到阶段、错误码、相关路径和报告位置。诊断保存失败单独报告，不覆盖原始连接失败原因。

## 验证范围

本次生命周期与恢复新增11项及既有73项相关回归通过，共84项；覆盖原进程句柄退出、PID身份不符、计算中自行停止、停止标记响应、真实网络锁释放、窗口存在时不处理、路径/心跳/元数据不足不处理，以及旧文件字节保持。旧Excel单独11项也通过；两工作区实际PowerShell参数/创建时间、恢复默认只读CLI、两版App离屏错误说明通过。恢复测试只请求本次创建的合成子进程自行退出，没有停止用户进程或在公司实盘执行恢复。

文件使用进程诊断新增9项用例与原17项连接诊断回归通过，共26项：真实Windows字节锁、查询后锁仍有效、释放后使用者消失、不同路径结果隔离、带引号模块、中文/空格/特殊字符路径、权限失败、列表变化和超时均已检查。两工作区的原配置无联网CLI链通过，44个原配置/参考/索引文件未变。所有原生查询仅作用于自己的查询会话，不结束用户进程；本机运行结果不代替公司的进程和网络证据。

本地用隔离数据测试：扫描被停止而旧缺口为0、真实Windows字节锁、文件拒绝访问、套接字权限错误、超时/TLS/HTTP状态、清理失败和错误Python依赖。Excel 的实际启动子进程与PowerShell格式化、两版App共用向导的离屏异步回填均已核验。未访问公司真实接口、修改原数据/配置、打开可见窗口或切换VPN。公司具体故障结论以该机返回的新报告为准。
