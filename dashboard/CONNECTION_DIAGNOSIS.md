# 历史扫描与公司实时连接诊断

2026-10-23：Excel 与两版本地 App 共用新的扫描结果和验证诊断。公司10:17报告已定位到 `network_session/writer.lock` 的字节锁申请，HTTP尚未发出；仍需该机查询文件使用进程以确认持有者。开发机的网络结果不能作为公司原因的证据。

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

`--lock-owners` 不隐含 `--connect`。它通过Windows自带的 [Restart Manager资源查询接口](https://learn.microsoft.com/en-us/windows/win32/api/restartmanager/nf-restartmanager-rmgetlist) 取得各锁文件的使用进程PID与创建时间，再用本机CIM补充Python/Excel及相关PID的程序路径、父PID、创建时间、看板模块名。模块识别兼容带引号的参数；完整命令行、其他参数、进程窗口标题和文档名不进入报告。查询只建立并结束自己的系统查询会话，不调用关闭/重启应用接口，不结束业务进程、不删锁文件、不弹窗或申请提权。

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

文件使用进程诊断新增9项用例与原17项连接诊断回归通过，共26项：真实Windows字节锁、查询后锁仍有效、释放后使用者消失、不同路径结果隔离、带引号模块、中文/空格/特殊字符路径、权限失败、列表变化和超时均已检查。两工作区的原配置无联网CLI链通过，44个原配置/参考/索引文件未变。所有原生查询仅作用于自己的查询会话，不结束用户进程；本机运行结果不代替公司的进程和网络证据。

本地用隔离数据测试：扫描被停止而旧缺口为0、真实Windows字节锁、文件拒绝访问、套接字权限错误、超时/TLS/HTTP状态、清理失败和错误Python依赖。Excel 的实际启动子进程与PowerShell格式化、两版App共用向导的离屏异步回填均已核验。未访问公司真实接口、修改原数据/配置、打开可见窗口或切换VPN。公司具体故障结论以该机返回的新报告为准。
