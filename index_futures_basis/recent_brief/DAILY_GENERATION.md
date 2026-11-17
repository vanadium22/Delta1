# 每天生成基差简报

使用已有 **工作自动化工作台（Work Automation 0.6.0）**。本机已找到桌面快捷方式，目标为 `P:\project\swhy\project\work_automation\启动工作自动化工作台.vbs`；公司原应用目录为 `D:\WORKSPACE\MAIN\SwhySc\project\work_automation`。本次只读检查了本机任务登记，未发现基差任务；公司实际任务列表需按程序路径查重。

## 立即生成

公司先在原仓库根目录 `git pull --ff-only`，登录Wind终端，然后双击：

```text
<仓库根目录>\index_futures_basis\start_recent_brief_daily.cmd
```

这个入口先复用原基差程序的Wind增量补缺（日历、实际合约、到期日、期现货收盘和持仓），再按逐日实际合约补最近80交易日成交量缺口，随后生成图片、卡片和图文；已有有效行情直接复用。沿用原`python.local.txt`或`SWHY_DELTA1_PYTHON`解释器配置，无需更换Work Automation自己的Python。无须每次导入快照或手填报告日期。

已经由其他程序更新好行情时，双击 `start_recent_brief.cmd` 即可只用本地生成。

## 在自动化App里每日定时

1. 打开桌面的“工作自动化工作台”，进入“定时子任务 → 登记子任务”。如已有同一基差程序登记，编辑原任务。
2. 按下表填写，点“检查配置”和“保存”。新任务默认暂停，保存不会执行。
3. 登录Wind后点“运行一次”，从日志和简报核对实际行情日、分红日期及退出结果。
4. 使用下表建议日程，启用自动运行；让工作台后台在该时点保持运行。关闭前端页面仍保留后台，完全关闭应用会停止调度。

| 字段 | 填写内容 |
| --- | --- |
| 名称 | 股指基差每日简报 |
| 程序 | 选择本仓库的 `index_futures_basis\start_recent_brief_daily.cmd` |
| 参数 | 留空 |
| 工作目录 | 仓库根目录，即包含`index_futures_basis`的目录 |
| 执行方式 | 建议“工作日”，北京时间16:10；可按自己的数据更新时间调整 |
| 程序类型/环境 | CMD任务，由启动脚本复用基差项目的现有Python |
| 邮件关联 | 不关联；本任务只生成文件 |

本机程序完整路径：

```text
P:\project\swhy\Delta1\project\index_futures_basis\start_recent_brief_daily.cmd
```

按公司现有仓库位置，程序为：

```text
D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard\index_futures_basis\start_recent_brief_daily.cmd
```

公司工作目录为 `D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard`。仓库实际位置不同就选择自己的文件。CMD参数每格一个值，不手工加外层引号。自动化App负责唯一调度，本入口不会安装Windows计划任务。

定时子任务使用这份单次入口，运行完成会退出；`start_recent_brief_watch.cmd`是持续监控本地输入的常驻方式，不用于工作台串行定时队列。

## 每天查看结果

固定打开：

```text
<仓库根目录>\index_futures_basis\exports\recent_brief\latest.html
```

它指向最近成功生成的批次。每次批次保留4张PNG、4份SVG、图文页、计算及卡片CSV、来源清单。报告标题和页首注明实际行情截止日及分红表日期。

正常退出码为0；Wind更新失败或不完整，但使用本地数据生成了报告时为2，页面和`run_manifest.json.market_refresh`说明状态及原因。有输出不代表行情已更新到当天，应核对报告日期。公司Wind实连、权限和实际数据更新速度仍以现场运行为准。

工作台0.6.0按工作日安排时仍可能在交易所节假日运行；报告会标实际可用行情日。它错过定时不自动补跑，如需当天补做，在任务界面按已有批次/新建批次规则运行一次。保持原有日报、FOF及邮件任务不变。
