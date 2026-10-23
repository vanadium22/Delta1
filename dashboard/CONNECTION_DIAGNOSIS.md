# 历史扫描与公司实时连接诊断

2026-10-23：Excel 与两版本地 App 共用新的扫描结果和验证诊断。公司电脑上的 `PermissionError` 尚需该机的新报告定位；开发机的网络结果不能作为公司原因的证据。

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

本地用隔离数据测试：扫描被停止而旧缺口为0、真实Windows字节锁、文件拒绝访问、套接字权限错误、超时/TLS/HTTP状态、清理失败和错误Python依赖。Excel 的实际启动子进程与PowerShell格式化、两版App共用向导的离屏异步回填均已核验。未访问公司真实接口、修改原数据/配置、打开可见窗口或切换VPN。公司具体故障结论以该机返回的新报告为准。
