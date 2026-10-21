# 日报同步与统计附件：Work Automation 0.6.0 接入交接

2026-10-21。用户确认**公司电脑已有计划**；本机看不到该计划的名称、ID、状态或触发时间。此次只交付源项目适配程序、暂停配置规格及交接提示词，未运行真实日报、发送邮件、安装环境、创建/启用/停用任何调度。

公司只读盘点等待问题已补丁处理：查询改用 Task Scheduler COM，20秒查询及2秒清理各自限时，超时/用户中断仍输出项目 JSON，计划状态标为 `complete=false`，不能当成没有计划。可先执行 `run_daily.cmd --inspect` 获取不依赖 Windows 查询的项目报告；`--inspect --windows-tasks` 再附计划结果。工作台独立盘点复用 `inspect_automation.py --tasks-only --match <入口路径>`，不读取项目配置或更改调度。具体实现依据 [Microsoft 只读枚举示例](https://learn.microsoft.com/en-us/windows/win32/taskschd/displaying-task-names-and-state--scripting-)。

## 可直接交给 Work Automation 负责对话的提示词

> 请将公司电脑已有的日报计划接入 Work Automation 0.6.0，沿用已有计划身份，只准备默认暂停的接入配置，保持现有计划原状。本轮先检查，不运行真实日报、不发邮件、不创建或安装环境、不启用或另建调度，也不要擅自停用现有计划。
>
> 请读取日报项目 `script_making/WORK_AUTOMATION_HANDOFF.md`、`work_automation.paused.example.json`、`daily_job.py`、`inspect_automation.py` 和 `run_daily.cmd`。任务目标是每天定时同步四类 Excel，然后生成 pnl1、两份独立风险统计、今年的总盈亏/当日盈亏双轴图及邮件所需附件草稿。源程序不发送邮件、不自带定时器。
>
> 公司仓库已确认是 `D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard`，日报模块为其 `script_making` 子目录。先在公司只读运行 `script_making\run_daily.cmd --inspect --windows-tasks`，核实实际解释器、配置和匹配的 Windows 计划；再检查 Work Automation 自身、旧 BAT/PS、启动文件夹及其他调度器是否指向同一业务。该命令的匹配结果不是完整计划清单，也不代表未匹配的任务不存在。
>
> 请交回唯一调度来源、现有计划 ID/启用状态/触发器/下次运行/最近记录，以及解释器完整路径、运行账号、工作目录、环境变量名称、北京时间执行时点、交易日与漏跑策略。未知值明确标为待确认，不猜测。不要把源码中的解释器候选当作公司已验证路径。
>
> 暂停规格文件是交接字段说明，不是已经验证可导入的 Work Automation 原生 JSON。请核对 0.6.0 实际格式后转换，并保持 `enabled=false`。确认唯一调度来源且得到接管授权之后，业务入口才使用 `script_making\run_daily.cmd --run`。默认不传截止日期，由程序取北京时间今天，各来源选择其之前最新实际报表；T-2 延迟按实际报表日期披露。请用同一固定解释器和工作目录等待进程退出，保存退出码及标准输出，不用 `start` 放走子进程。先做本文列出的合成测试，不以真实任务试跑代替测试。
>
> 退出码 0 为生成成功或同输入复用，1 为异常失败，2 为下载/统计不完整而未生成可发送草稿，3 为同目录已有批次运行。不要把退出码2/3当成成功，也不要自行重试、补跑或新增备用调度。需要邮件发送时另行接入并确认授权；本程序只生成 `.eml` 和附件。

## 1. 已有计划与触发入口

| 项目 | 当前证据 |
| --- | --- |
| 公司已有计划 | 用户确认存在；计划名、ID、启用状态、执行账号、调度器、下一次时间及执行记录均待公司核实 |
| 本项目内部日历调度 | 没有 cron、APScheduler、Windows注册任务或每天定时循环 |
| 桌面正常启动 | 自动检查一次原双表和两个新增来源；没有“下次固定时间”，下次触发是下次打开App |
| 桌面手动同步 | 用户按钮触发；原两份表配对，新两类独立；普通刷新本地不访问公盘 |
| 命令行入口 | 原 `sync_worker`、兼容 `app --sync-once`，本次新增 `daily_job --run` 单次入口；本身均不注册计划 |
| 统计触发 | 主窗口统计页自动生成一次/手动生成；单次CLI在同步全成功后生成统计及草稿 |
| 已有执行证据 | 原日期目录manifest、新来源status/manifest；新单次任务有daily_runs记录。当前机器没有公司调度记录可供核实 |

接管前按实际程序路径、工作目录、参数及数据目录查重，不能只按任务中文名。GUI启动检查仍保留，没有擅自关闭；它和CLI同步共用文件写锁。CLI额外持有同一数据目录的批次锁，成功输出按内容指纹复用。**锁与去重不能替代确认唯一调度来源。** 如以后要关闭GUI自动检查或迁移旧计划，交给接管对话在获得授权后操作。

## 2. 目录与解释器

| 内容 | 路径/状态 |
| --- | --- |
| 公司仓库与CLI工作目录（既有项目记录确认） | `D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard` |
| 公司模块 | `D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard\script_making` |
| 单次适配器 | 上述模块 `run_daily.cmd` / `daily_job.py`，也可在仓库根目录执行 `完整python路径 -X utf8 -m script_making.daily_job` |
| 只读检查 | `run_daily.cmd --inspect --windows-tasks`；或 `-m script_making.inspect_automation --windows-tasks` |
| 原桌面 | `script_making\start.cmd`，会启动窗口，**不适合作为无人值守批次入口** |
| 公司Python实际完整路径 | **待公司检查确认**。原启动器已有候选 `D:\conda\envs\swhy_delta1\python.exe`，本次没有实连验证 |
| 本次合成测试已用解释器 | `P:\code_content\python_work_env\conda_env\swhy_delta1\python.exe`，仅开发机，不能复制成公司配置 |

`run_daily.cmd` 沿用原 `resolve_python.cmd`，不安装环境；执行顺序为 REPORT_APP_PYTHON、SWHY_DELTA1_PYTHON、本机python.local.txt、上述公司候选、已登记环境及PATH。接入时请固定已验证的完整解释器路径（可写python.local.txt或设置对应变量），不依赖不确定的PATH。已有依赖为 openpyxl 和 PySide6-Essentials，无新增包。

## 3. 实际参数、环境与无人值守行为

| 参数 | 行为 |
| --- | --- |
| 无参数 / `--inspect` | 默认只读检查；不实例化会迁移数据的Settings、不读Excel、不访问公盘、不导出统计 |
| `--windows-tasks` | 仅检查模式。只读查询当前电脑名称/动作匹配“日报”或script_making的Windows计划，最多20秒，不打印任务动作参数或密钥 |
| `--run` | 执行一次：配对同步收益互换/复核表 → 盈亏统计 → 策略台日报 → 统计 → 四张PNG及邮件草稿。没有发信代码 |
| `--root PATH` | 本机配置所在模块目录；默认模块自身。CMD已传入实际模块目录 |
| `--as-of YYYY-MM-DD` | 业务选择截止点，不含该日，默认北京时间今天；不是强行指定某日报日期。原双表选截止前最新上游日期，新来源按现有增量规则发现；本地统计只取截止前文件 |
| `--local-only` | 必须同时显式`--run`；跳过公盘，只使用本地数据，但仍写记录和附件。用于隔离夹具测试，不是纯检查命令 |
| `--help` | 显示帮助，不执行业务 |

原 `sync_worker` 仍支持 `--root`（必需）、`--kind pnl/strategy`（省略代表双表）、`--only-missing`（保留兼容；现在也核对公盘修订）、新增 `--as-of`。直接运行它仅同步，不生成统计；它的单次部分成功可能以0退出并在result.errors列出，**中央调度应使用daily_job，不只依赖sync_worker退出码**。

| 环境变量名称 | 用途 |
| --- | --- |
| REPORT_APP_PYTHON / SWHY_DELTA1_PYTHON | 指定现有解释器 |
| SCRIPT_MAKING_SOURCE / SCRIPT_MAKING_DATA | 覆盖原共享来源 / 实际本地日报目录 |
| DELTA1_DATA_ROOT / DELTA1_OUTPUTS_ROOT | 公共数据与输出根目录 |
| QT_QPA_PLATFORM | 单次导出默认使用offscreen，不显示窗口 |

不读取/输出邮箱密码或密钥。子进程使用冻结的配置和绝对保存目录，避免环境变量再次覆盖导致同批次写到不同位置。CMD等待Python退出、保留退出码，不pause、不脱离进程。服务账号须已有共享目录读取及本地目录写权限，不依赖Y盘简称或交互式Excel/Wind。

## 4. 北京时间、日期规则、漏跑与耗时

- 调度时间：**未配置，待公司核实已有安排**；本次未新增计划，也没有安排“明天第一次运行”。时区固定按Asia/Shanghai说明，程序取UTC+8业务日期。
- 工作日/交易日：源程序不另维护交易日历，也不把周一至周五当交易日。日期按截止前实际发布文件决定，允许T-2；两个风险来源及pnl1分别披露日期。需由负责对话确认公司已有交易日/节假日调度规则。
- 历史图：今年本地已有报表，截止各自所选日期；每一天按当前阈值及剔除规则独立筛选观察标的，缺失日期不补零。原表T-2注释不改变为报表日收益。
- 漏跑：CLI不自动补跑/重试。新两类首次近7个自然日，之后增量、近周重查及失败日期补齐；原双表只取最新有效日期，不自动补齐所有漏掉历史日。以后需要补跑特定区间，由负责人明确日期与次数再运行，不另建补跑调度。
- 耗时：公司实测未知。本机合成测试不是典型业务耗时。三个同步子进程各限45/120/120秒（顺序执行，均会检查），首次全年历史解析取决于本地文件数量；后续按文件哈希与规则复用历史缓存。actual elapsed_seconds写入daily_runs，负责人据公司样本确定外层超时，并负责终止整棵进程树。
- 退出码：0成功/相同输入复用；1运行异常；2同步或统计不完整（含缺上期、跨年无法计算、历史解析失败），不发布新可发送草稿；3已有批次运行。互斥拒绝不覆盖正在运行者的latest.json；参数格式错误由argparse返回2，stdout不会伪装成成功。

## 5. 输入、输出、副作用与恢复

- 输入：原`config.local.json`、`statistics.local.json`、公共数据配置以及既有公盘与本地Excel。无参数检查不读取业务Excel、不枚举网络数据目录。
- 默认数据：公司仓库`data/reports/swap`，但必须以检查命令返回的data_directory为准，可能有自定义路径。新日报位于其`downloads/pnl`与`downloads/strategy`。
- 公盘修订：有效新内容通过文件稳定性、工作簿/日期及SHA256校验后替换当前本地文件。旧版留在各归档根的`_revisions/日期/旧哈希/原文件名`；同内容复用不重复复制。新来源多个目录的版本按最新修改时间选择，最新时间相同而内容不同会失败，不任意猜测。
- 记录：实际数据目录`statistics/records/<ID>.json`；全年汇总缓存`statistics/history_cache`；单次任务日志`statistics/daily_runs/<runID>.json`及`latest.json`；成功指纹索引在`daily_runs/completed`。stdout只输出状态、runID、结果目录等，不打印报表值或邮件地址。
- 附件：`statistics/exports/<生成时间-ID>/pnl1.png`、`risk.png`、`swap_pnl_history.png`、`strategy_pnl_history.png`；另有`邮件草稿.eml`、`邮件正文.txt`、统计记录和邮件设置。草稿本身附上述四张PNG；没有上传或发送动作。
- 副作用：显式运行会下载/更新本地文件、保留旧版、写JSON/PNG/EML及公共数据登记；不写业务数据库、不上传、不发邮件。不运行原材料脚本。不自动安装Python/Conda、包或计划任务。
- 互斥：同一数据目录的`statistics/.daily_job.lock`覆盖批次；原双表及两来源各有跨进程writer锁。配置在批次开始冻结。外部计划应使用同一真实目录、账号及解释器，不以改保存目录规避锁。
- 去重：来源文件哈希、选定日期、统计/邮件设置及全年参与文件指纹一致时，校验已导出文件哈希后复用旧结果；公盘修订、规则变化或导出损坏会生成新的独立目录，保留旧件。
- 失败：三个来源逐一检查，任一不完整则记录退出2，不把旧统计当本次成功。统计不足也退出2；失败导出目录带“导出未完成.txt”。完成索引只在全部附件写完后登记。再次显式运行重查来源及失败日期。双表先全部校验，正常异常回退已替换项；被外部强制终止时可能留下暂存目录，下一次会重新校验并收敛到公盘，旧版备份保留，不自动删除。

## 6. 暂停配置与负责人操作

随附 [work_automation.paused.example.json](work_automation.paused.example.json) 明确enabled=false、现有任务ID/时间/公司解释器为null、native_schema_verified=false。它是交接规格，**不可宣称已导入或已启用Work Automation**；负责人须依据0.6.0实际格式映射。

本项目的最小适配已完成：同步修订覆盖、可检验的单次运行入口、无窗口统计导出、批次锁、退出码、运行记录和结果去重。没有创建任何调度器或发送邮件。剩余操作依次为：公司只读盘点 → 确认旧计划身份及唯一调度来源 → 固定解释器/账号/目录 → 确认时间与漏跑策略 → 映射暂停配置 → 合成验收 → 接管授权后再更改现有计划并启用。

无副作用核查命令（公司仓库根目录）：

```bat
script_making\run_daily.cmd --inspect --windows-tasks
```

合成测试使用已有解释器，在隔离临时目录生成虚构Excel，模拟共享来源或mock子进程，不访问公盘、不发邮件、不登记计划：

```bat
"已核实的python.exe完整路径" -m unittest script_making.tests.test_report_updates script_making.tests.test_statistics -v
```

本轮执行的是上述合成验证及只读检查，不是公司计划试跑。真实输入、输出、收件人、共享前缀及自动化运行记录均为本机数据，不纳入Git。
