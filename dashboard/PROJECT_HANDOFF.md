# Delta1 公司看板当前交接

2026-10-29。基线为已发布f345174b07d7acea469d6ba1655e8f7355792ce3；本轮接续真实公司ZIP和ETF截图，提交时保留并继承并行日报/统计提交8f658f9，发布批次 `2026-10-29-company-feedback-safe-shutdown-and-evidence`。统一分支codex/company-apps，实际提交号看最新Git/远端及交付回复；精确文件清单见APP_RELEASE.latest_update.files。公司验收按下列证据逐项判断。

## 本次公司证据

完整解析24个JSON，包SHA256为2838eb4a803ff624f096f5af3d19b5148769e2df20da8b46d6e40c8ff0dff99b，return_manifest缺失清单为空。五次diagnosis及git.json均为f345174，实际Python为D:/conda/envs/swhy_delta1/python.exe，原配置SHA一致、未改写。用户确认取样时窗口开着，关闭约1–2分钟。

| 项目 | 已确认 | 仍有缺项 |
|---|---|---|
| Y盘分红 | Share complete、无错误；Import新增16条，库由16增至32；B1为2026-10-27，当前16合约选到新D | 本次年份目录只匹配1份表；历史D缺556行，不能以最新表回填旧日 |
| 四档分位 | 16个连续档位的20日窗口完整，历史日线真实缺价0 | 16个60日窗口均缺早期D；缺D不触发重复DDB下载价格 |
| 主行情/页面 | 两次样本32标的新鲜且源时推进；同配置App collecting、closing=false并有页面应用时间，用户确认开窗 | 两样本和截图不认证10–15分钟全部持续运行或新关闭耗时 |
| 行业 | 300/50/500/1000名单齐；有效涨跌300/50/500/997；可查看行业及已有权重 | IF/IC/IM缺权重1/2/2且行日期混合；IH权重日期09-30，未滚动至准确昨日；分类缺17/2/49/148 |
| ETF | 四指数各前三，价格已显示；同日10-28 NAV/未复权close配对12/12，Nav显式阶段通过 | 盘中IOPV、份额/单位/拆分、带日PCF定义未配置，仍mapping_required |
| 收盘折溢价 | 用户截图明确三只IF ETF为−20.0/−19.8/−18.2 bp，日期10-28 | 大字空白是盘中折溢价，不能用收盘NAV填成IOPV |

正确源仍为 `Y:\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026`。本次drive_y.json实际记录DisplayRoot为 `\\192.168.91.230\FTPServer`，这是现场证据，未猜拼、改源或重新映射。匹配指数基差情况_*.xlsx，业务日以Sheet1!B1为准。旧默认运行时迁移、自定义/空白保留及SourceDirectory/InputFile语义继续。

## 本轮修正

1. 关闭等待有一个已复现的耗时点：成分存储逐股写Parquet、逐文件提交目录。新增App专用EquityObservationStore，最多4个文件写入者并行、每64个已完成文件批量提交SQLite目录；共享RealtimeStore默认行为/格式不改。关闭等待全部文件写入者结束，原始响应与已提交SQLite完整保留，异常留下未登记文件可从SQLite重放，不强杀、不删锁。
2. 增加成分状态/归档进度、关闭等待阶段和秒数；所有工作排空、model.close结束后写phase=closed与shutdown.complete/elapsed_seconds。原历史closing文件不再是新运行最终状态的唯一证据。
3. 诊断完整名单与权重有效性分开：本次四组名单已知，不再因缺权重将股票缺口总数误报未知。历史慢读前冻结成分快照；若快照晚于检查起点，质量明确未知，不误报全体陈旧。30秒/3秒质量门槛不放宽。
4. UI把大字空项标成“盘中折溢价”，收盘折溢价仍独立显示真实日期和数值。默认离线Overview新增逐ETF实际NAV/同日收盘/溢价、页面引擎ETF预览及安全关闭/归档证据；计算逻辑不把NAV冒作IOPV。
5. 公司步骤默认Runtime复测，只需更新、正常开窗Overview、正常关闭、关闭后Overview和安全JSON ZIP；Full模式保留原完整数据阶段。ZIP核对同一运行记录的开窗与最终排空，不额外重跑已通过的Y/Wind阶段。

98项受影响回归通过（20.927秒，无跳过，ResourceWarning作为错误）。同机1800标的隔离归档从8.884秒降至2.489秒，保持1800个原格式Parquet；这是合成数据本机结果，不能承诺公司耗时或认定逐股归档是唯一现场原因。实际公司关闭等待阶段由下一包确认。1580/860宽窄ETF页已离屏查看，未改用户截图。

## 下一步公司复测

执行 [APP_COMPANY_TEST](APP_COMPANY_TEST.md) 第1、4、5节，默认runtime。保留Wind登录、实时VPN手动：

1. 正常关闭旧看板、等后台退出，再git pull --ff-only，创建新时间目录并记录新HEAD。
2. 正常开窗运行，核对收盘与盘中两种溢价标签、行业缺项说明；保持窗口开着导出Overview。
3. 正常关闭，观察归档/等待进度，等窗口自行退出，再执行一次离线Overview取得最终关闭报告。
4. 只回传白名单JSON ZIP。打包脚本核对同一App报告路径出现开窗和shutdown.complete，缺失照实记录，不补造通过。分红/Wind阶段按需选择full；当前Y读入/NAV成功不必反复测试。

若公司可提供正式Wind代码生成器/源说明，后续再核验缺失权重和IOPV/份额/PCF字段及单位。当前没有可靠定义，不能猜字段或拿成交量/规模变化替代。历史D须真实旧表，当前年份目录的一份表不能恢复全部历史。

## 路径与保护

本机统一工作区P:/project/swhy/Delta1/company-apps-worktree；公司Git根D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard，LocalRoot为其下dashboard/localsetting/app。入口仍dashboard/start_presentation.vbs、public主题。本机原配置P:/project/swhy/Delta1/project/dashboard/localsetting/native.json。

保留逐日D、连续00/01/02/03的20/60、简单去分红年化100*(F-S+D)/S*365/T、当前定价日排除、T<5单列及非交易合法参考；缺价/映射/D不跳过，明确0优先、缺D仅向当时已知前序到期合约继承，新D不回写过去。研究32项/A02暂停保留，原独立App/Excel不动。

主HTTP三秒、成分一分钟；默认Overview离线，自动Wind低频，实时VPN手动；DDB仅实际缺口按原授权准备，HTTP失败不切DDB。原数据/缓存/配置/凭据/Excel、其他worktree及四份提示词不动，不reset/clean、全量stage、强推。

本次输入、逐JSON SHA/节点索引、冻结证据、原件保护、性能和测试日志仅在忽略的local_artifacts/validation/company_feedback_20261029。旧7份说明和MANIFEST不变，仍见 [唯一归档](../docs/archive/2026-10-29/README.md)；不再复制旧长文。此前f345174的55项及229/62/272项均属对应批次历史。

新对话先读 [接续提示词](docs/NEXT_COMPANY_RETEST_PROMPT.md)、本页、AGENTS与APP_RELEASE，再核验最新Git/远端和新公司包，不从旧版本重新实现。
