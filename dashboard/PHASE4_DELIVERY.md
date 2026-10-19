# 双 VPN、IF 分位诊断与本地两版交付

记录日期：2026-10-19（Asia/Shanghai）。先核对实际工作区，基线 HEAD 为 `77f716b`；原有其他业务修改未纳入本次范围。此文件不含逐笔行情、历史数据或凭据。

## 已实现的共同启动流程

`dashboard/start.cmd` 首先显示“检查并补齐历史 / 跳过，使用现有历史 / 取消”。此时不会启动实时采集、历史下载或自动合约联网查询。

选择补齐后，用户在客户端登录 DDB VPN 并确认。独立维护进程按现有路由和本机加密数据库配置工作；完整历史不重复下载。页面显示目标日期、剩余缺口、失败、滞后及重试时间，支持立即重试、停止补库后继续、取消启动，以及本机账号设置。

正常完成、跳过中途任务或关闭窗口，都必须等子进程退出并回收后才显示公司 VPN 步骤。页面暂停、状态写入 complete 均不能替代进程退出。SDK 阻塞时沿用受控进程超时终止，已发布版本保留。

随后由用户断开 DDB VPN、登录公司 VPN；一次有限 HTTP 请求验证当前四指数及16个合约的身份和有效价格，关闭探测会话后才允许持续采集。失败可重试或离线进入。离线后点击“开始实时”仍须验证。程序不操作或保存 VPN 登录信息。

同一配置目录使用实例锁；重复双击激活已有向导或窗口。若激活失败，不再创建第二个采集实例。维护和实时任务额外以实际历史目录的跨进程锁互斥。开发版维护页在实时阶段不会直接启动 DDB；需要补库时关闭看板并重新走启动向导。独立 `maintain_history.cmd` 保留。

`--no-realtime` 保留向导但不自动开始持续采集；`--capture` 和 `--startup-check` 是不联网的验证入口。

## IF 专项结论与证据边界

用户补充00、03均出现过0%，原观察时点未知。冻结本机保存行情后，四档逐日映射、F/S/D/T、分红继承、T<5、定位日排除、单位、同步、陈旧、缓存与显示分别核验。

- 保存行情回放的00、03分位均为10%；独立计算与代码一致。00有效n=10，03有效n=20。
- 同日保存观测中，00有234个有效观测，03有230个有效观测，分位最低均为10%；未复现实时0%。
- 陈旧行情回退到历史定位后，03可以复现0%：历史定位值低于全部20个样本，独立值、代码与整数显示一致。它不是当前实时分位。
- 00的原反馈仍未复现；03的历史回退仅是一个已证实场景，不能认定就是原反馈原因。不修改合法0，不把NaN补0。

私有证据仅在 `dashboard/runtime/diagnosis_20261019/`：`IF_诊断报告.md`、`diagnosis.json`、`IF_20d_daily.csv`、`IF_20d_historical_marker.csv`、`snapshot.json`。原始业务数据不进Git或代码bundle。可运行 `python -m dashboard.percentile_audit --output <项目内目录>` 重新冻结；该命令只读本地行情和已发布历史，不下载。

## 首阶段两版与静态 Excel 记录

下列静态Excel说明是首阶段归档。后续已实现独立自动刷新数字版和指标，使用方式及当前发布范围以 [NUMERIC_EXCEL.md](NUMERIC_EXCEL.md) 为准；新两版前端仍仅本地。

- 展示版：`start_presentation.cmd` / `Delta1 展示版.lnk`，青色 Δ 图标。最新连续档位计算的四品种数字、分位、有效n及数据状态；无账号、连接地址或维护路径入口。
- 开发版：`start_development.cmd` / `Delta1 开发版.lnk`，蓝色 D 图标。保留最新研究页面、指标解释、数据管理、维护和本机凭据设置，新增导出快照。
- 两版共用同一实例；第二次打开激活正在运行的版本。切换版本请先正常关闭已有窗口。没有恢复已退役旧界面。
- `runtime/数字看板_20261019.xlsx`：16行四品种四档数字、64行分位窗口，两张表、零图表。包括行情/指数、分红与继承、基差点/bp、年化、20日及3/6/12月分位、n、时点和状态。当前交付明确标注为保存行情冻结回放，不是实时连接。
- 数字快照由窗口导出；`export_numeric.cmd <snapshot.json> <输出.xlsx>` 重复生成Excel。本机导出依赖 Node 与 `@oai/artifact-tool`；公司电脑没有此运行库时不能直接使用导出器。无需在公司联网读取本次Excel。
- Excel在生成库重新打开逐值核对，并在Microsoft Excel独立隐藏实例中只读打开核验；界面及各表已截图检查。

当前前端未提交清单（数字模块已另行纳入白名单）：

```
dashboard/current.py（仅窗口注入、标题/图标及冻结/展示入口参数这些增量；共同启动修改单独提交）
dashboard/native/editions_current.py
dashboard/start_presentation.cmd
dashboard/start_development.cmd
dashboard/create_edition_shortcuts.ps1
dashboard/assets/presentation_current.ico
dashboard/assets/development_current.ico
dashboard/Delta1 展示版.lnk（忽略）
dashboard/Delta1 开发版.lnk（忽略）
dashboard/runtime/numeric_export/build.mjs 及依赖链接（忽略）
dashboard/runtime/数字看板_20261019.xlsx、快照、诊断及截图（忽略）
```

原来就存在的 `excel_sample.mjs`、`indicator_guide_work/`、`ohlcv_oi_research/`、`research_v3/` 以及其他业务模块改动继续保留，不作为本轮成果提交。

## 验证与限制

启动选择前无任务、补库退出后才切换提示、取消等待、失败重试、非法价格拒绝、互斥锁、缺失与0区分，以及历史维护、分红、换月、分位、数据包安装均执行回归。另在不含未提交前端文件的隔离源码目录验证共同启动和计算代码，实际计数及本地提交见 GIT_WORKFLOW.md。

本轮没有切换两套VPN，也没有为了验收重新登录公司或DDB；真实VPN切换端到端需用户在客户端操作。程序流程及关闭顺序已有自动测试，不能将其描述成实际VPN切换验收。本轮没有安装到公司目录；既有增量安装器与Wind保留回归继续验证，原数据zip哈希未变。

最新授权允许推送数字Excel及必要后台，并更新离线bundle。两版新前端、实际业务Excel、历史/实时数据和凭据仍不进入Git或代码bundle；唯一Excel例外是无业务数据的空白数字模板。
