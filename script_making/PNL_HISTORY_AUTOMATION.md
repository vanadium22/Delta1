# 本人专用：场外业务及各组收益历史定时任务

此任务独立于已经跑通的日报。现有日报仍生成 `pnl1.png`、`risk.png`、`swap_stocks.png`，原收件人、09:20计划及FOF沿用。日报盈亏表现在用TMT、消费、周期三行替换境内个股期权台汇总行，其中消费合并“消费＋周期-消费代管”，周期合并“周期＋周期-其他”；原始五行不会重复参与组汇总，合并行保留来源行号。

新增任务仅同步既有来源的盈亏统计，生成两张图：

| 文件 | 内容 |
| --- | --- |
| `otc_pnl.png` | 场外业务合计的当年累计净利润折线及相邻报表变动柱 |
| `groups_pnl.png` | 原表各组的同类历史图，每组独立面板；包括TMT、合并后的消费和周期，不再重复计入境内个股期权台 |

历史从北京时间当年1月1日至本次实际来源日期，不限30份。使用Excel已保存的数值缓存、不重算公式；保留原T-2、缺日区间和跨年重置规则，缺失不补零，不跨失败点相减。分组结构、合并来源或关键缓存无法可靠确认时，记录诊断且不生成可发送结果。个别组历史上尚未出现或已经消失时，对应日期断线，首次出现或重新出现的日期不计算差额。

新任务程序只生成，不接SMTP。两图以CID内嵌，保留纯文本后备；Work Automation使用原邮件服务发送。收件人仅取新任务独立设置中的一个本人地址，不读取日报收件人，不配置抄送/密送。

## 1. 更新日报代码

在日报App空闲并关闭后执行；命令不打开程序或后台。Work Automation已具备所需邮件协议，本次无需更新它。

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
git pull --ff-only origin codex/company-apps
if ($LASTEXITCODE -ne 0) { throw '日报更新失败' }
```

## 2. 保存新任务的本人邮箱

沿用原日报任务已经验证过的Python环境。公司此前核实为 `D:\conda\envs\swhy_delta1\python.exe`；如原任务中的实际路径不同，使用原任务路径。

以下只保存新任务邮箱并检查配置，不抓取、生成或发信，不启动工作台。输入框中填写你自己的完整邮箱，不能填写多人地址。

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
$taskPython = 'D:\conda\envs\swhy_delta1\python.exe'
$selfEmail = Read-Host '请输入仅接收新收益任务的本人邮箱'
& $taskPython -B -s -X utf8 .\script_making\pnl_history_job.py --set-self-email $selfEmail
if ($LASTEXITCODE -ne 0) { throw '本人邮箱设置失败' }
& $taskPython -B -s -X utf8 .\script_making\pnl_history_job.py --inspect
if ($LASTEXITCODE -ne 0) { throw '独立收益任务配置检查失败' }
```

设置保存在被Git忽略的 `script_making/pnl_history.local.json`，仅含 `to`。没有填写时任务会拒绝运行，不能回退到日报地址。原 `statistics.local.json` 不变。

## 3. 在Work Automation登记新任务

在“定时子任务”新建一个名为“本人场外业务及各组收益”的独立任务；已有同名同程序任务时编辑该任务，避免重复登记。保留原日报和FOF任务。

| 字段 | 填写 |
| --- | --- |
| 程序路径 | `D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard\script_making\pnl_history_job.py` |
| 任务Python | 与原日报任务相同的已有环境 |
| 工作目录 | `D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard` |
| 参数 | 只添加一格 `--run` |
| 执行方式 | 首次选择“手动” |
| 启用自动运行 | 首次不勾选 |
| 程序生成的邮件 | 首次选择“成功后仅生成发送预览” |
| 邮件来源 | 不关联邮件 |
| 预览收件人/主题/正文覆盖项 | 留空，使用程序生成的本人邮件 |

直接选上表中的新程序，它已处理包导入并支持工作台的 `--wa-output` 协议；无需使用原日报 `integrations/daily_report/entry.py`，无需手填 `--wa-output`。公司定时任务不填写开发验证用的 `--local-only`、`--root` 或 `--as-of`。

点“检查配置”及“保存”，然后“运行一次 → 提交 / 查看本批次”。这一次预览会真实同步盈亏统计并生成两张图，但不会发送。核对结果中的收件人只有本人，抄送/密送为空，附件只有 `otc_pnl.png` 和 `groups_pnl.png`。

## 4. 切换发送并设置时间

确认预览后，把此新任务的“程序生成的邮件”改为“成功后交给邮件服务发送”并保存。原预览批次已经完成，使用“运行一次 → 新建批次 → 确认 → 提交”执行发送流程；相同输入会复用两图，交给原邮件队列一次。

成功后把此任务执行方式改为“每天”，填写你需要的北京时间，例如 `09:30`，勾选启用并保存。新任务时间尚未替你在公司设置；原日报保持09:20。每天包含周末；选择工作日也不等于交易日历。同一输入已经发送时会复用原产物和发送记录，不会每天重复发送未更新的图。

新任务自行同步盈亏统计，不依赖原日报是否先运行。两者共用数据目录写锁，撞锁时退出3、不自动重试；查看已有运行结束后，用明确的新批次重新提交。无需新建Windows业务计划，沿用工作台已有登录启动和后台。

## 产物与故障检查

实际数据根目录下的独立位置：

- `statistics/pnl_history_exports/<时间-ID>/`：两图、邮件草稿.eml、邮件正文.txt、统计记录.json、邮件设置.json。
- `statistics/pnl_history_records/`：冻结来源路径/日期/哈希、各组原始行号和历史诊断。
- `statistics/pnl_history_runs/`：运行记录及完整文件哈希索引。
- `statistics/pnl_group_history_cache/`：按来源哈希和版本保存的组历史值缓存。

退出码0为成功/复用，1为失败，2为不完整，3为已有任务占用。同一目录的完整文件及哈希通过检查才可复用；失败或不完整不写本次工作台邮件结果，旧目录保留。遇到读取失败或组识别诊断，按运行记录中的原文件日期/行号核对，不把失败当作零值，也不删除旧批次、发送记录或已保存任务绕过去重。

### 不完整结果的只读诊断

工作台日志末尾的Conda错误会转述程序的非零退出码。若前面的JSON为 `state: incomplete`，实际原因以JSON为准。现在历史解析不完整时，日志直接包含异常日期、原始原因、错误份数及最新两期是否取得缓存/差额；当年只有一份报表时单独说明缺少上期。运行仍退出2，不交付可发送结果。

对于已经生成的统计记录，无需重新同步全年报表。在以下**单行**命令中，把 `<记录ID>` 换成日志 `statistics_record` 的实际文件名（不含扩展名）；解释器沿用已验证的任务Python：

```powershell
& 'D:\conda\envs\swhy_delta1\python.exe' -B -s -X utf8 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard\script_making\pnl_history_job.py' --diagnose-record 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard\data\reports\swap\statistics\pnl_history_records\<记录ID>.json'
```

此入口只读取指定JSON，返回诊断、日期和完整性标志，不输出利润金额或邮箱，不加载任务本机设置、不读取源Excel、不同步、不渲染、不发信、不写文件。诊断命令成功读取时退出0；`diagnostics.complete` 才表示已有记录的历史完整性。它不核验导出文件，也不提供邮件发送清单。错误类型或缺失JSON退出1。

保留原始 `errors` 及其报表日期，可直接反馈这部分输出以定位历史结构或缓存问题。已保存任务保持 `--run`；无需为了查看诊断而修改任务参数或计划。

本次验证为隔离数据、合成Excel和模拟SMTP；没有在公司创建任务或发送真实邮件。
