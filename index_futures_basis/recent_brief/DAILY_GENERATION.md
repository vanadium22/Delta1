# 每天生成Word和PDF基差简报

## 在基差App里操作

公司先在原仓库根目录执行`git pull --ff-only`，重开基差App，进入 **报告与记录**。

- **一键生成简报并打开PDF**：默认正式模式先增量更新Wind行情及成交量，然后后台生成Word/PDF并打开PDF。取消“正式模式先增量更新行情”只用本地；离线模式不联网，演示模式不生成真实简报。
- **查看最新PDF / 查看最新Word**：打开最近成功批次对应的文件。
- **打开简报目录**：查看该批次的Word、PDF、四张完整PNG/SVG、30/60/120日分位表CSV及来源记录。
- **修正图片后重排Word/PDF**：选择已修改PNG的批次，仅重排新Word/PDF批次并打开PDF；不重算、不下载、不覆盖原批次。
- **接入每日自动化**：在原“工作自动化工作台”登记唯一的单次CMD任务。新任务自动启用工作日16:10；已有同程序登记保留原ID、时间和启停，不重复创建。找不到工作台时选择其包含app.py的目录。

生成使用已有Python及项目已声明的python-docx/Matplotlib依赖，不需要Word或LibreOffice来生成PDF。Word与PDF同时生成完整后才替换latest；图片和文档布局分开，未来改图后可重新生成或重排。

日常并非固定使用前一日收盘：默认北京时间15:05前取上一已收盘交易日，15:05后尝试更新当日；16:10任务正常更新后通常为当日。离线或更新失败只使用实际本地日期，报告抬头直接列行情日。新版为11页：15号正文的综合观察首页、2页四品种当前合约及远减近跨期表、后8页图与卡片；每品种00/01与02/03年化接近才取简单平均；价格卡下方可核对同日指数、实际合约价格和最新本地分红点数。

## 已有工作自动化App

本机已登记并启用“股指基差每日Word与PDF简报”（工作日16:10），重复接入验证保留同一ID；没有启动后台或更改原邮件/日报/FOF任务。本机桌面为“工作自动化工作台”，源目录`P:\project\swhy\project\work_automation`；公司为`D:\WORKSPACE\MAIN\SwhySc\project\work_automation`。仍使用其0.6.0原生定时子任务，不另建Windows调度器、不接邮件、不更改日报或FOF。

公司更新基差代码后，在基差前端点一次“接入每日自动化”，再打开工作台“定时子任务”，会看到 **股指基差每日Word与PDF简报**。已有任务仍沿用自己的名字。可在此编辑时点、暂停/启用、运行一次和查看日志。接入按钮只登记任务，不启动工作台后台、不立即运行Wind；到点执行仍需Wind登录、工作台后台运行以及本机Python配置可用。

| 字段 | 默认值 |
| --- | --- |
| 程序 | 仓库内`index_futures_basis\start_recent_brief_daily.cmd` |
| 工作目录 | 仓库根目录，即包含index_futures_basis的目录 |
| 参数 | 留空 |
| 环境 | CMD，由启动脚本沿用python.local.txt或SWHY_DELTA1_PYTHON |
| 新任务时间 | 北京时间工作日16:10，启用；已有任务不改动 |
| 邮件 | 关闭，只生成文件 |

本机程序：`P:\project\swhy\Delta1\project\index_futures_basis\start_recent_brief_daily.cmd`。

公司程序：`D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard\index_futures_basis\start_recent_brief_daily.cmd`；公司工作目录为`D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard`。

手动也可双击`start_recent_brief_daily.cmd`；已经更新好行情时双击`start_recent_brief.cmd`。持续监控用的`start_recent_brief_watch.cmd`不放入工作台串行队列。任务单次完成后退出，正常0；更新不完整仍尽力生成且返回2，日志和报告标实际行情日期及失败原因。没有输出成功就不替换上次结果。

工作台工作日为周一到周五，交易所假期可能重复最近行情日，报告如实标日期；错过定时不会自动补跑。关闭工作台前端可保留后台，完全关闭会停止调度。公司Wind权限和实连仍需现场验证。

## 保存位置

本机固定文件：

```text
P:\project\swhy\Delta1\project\index_futures_basis\exports\recent_brief\latest.pdf
P:\project\swhy\Delta1\project\index_futures_basis\exports\recent_brief\latest.docx
```

公司固定文件：

```text
D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard\index_futures_basis\exports\recent_brief\latest.pdf
D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard\index_futures_basis\exports\recent_brief\latest.docx
```

每批次保存于`index_futures_basis/exports/recent_brief/行情日/批次/`，默认9页Word/PDF、4张完整PNG和SVG、8份分段排版图、计算/卡片CSV及来源清单。不生成HTML，新旧批次独立保留。前端从latest.json读取真实批次，所以不依赖特定预览日期目录。

生成时重新读取本地最新业务日期的分红，包含基差正式输入和看板已落地的分红缓存；不访问分红公盘。无需把最新文件手工钉到--dividends，日常默认按B1选最新。Word/PDF图片页只留图片与卡片及日期，全部图片后自动追加综合观察；规则和特征随narrative.json保留，分红校验CSV与源Excel快照同批次保存。
