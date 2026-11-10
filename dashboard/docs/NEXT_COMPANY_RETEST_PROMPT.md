# 下一对话：公司点击、稳定显示与规模饼图复测

2026-11-10。先完整读本页，再读根/dashboard AGENTS、PROJECT_HANDOFF、APP_COMPANY_TEST、APP_VALIDATION、APP_MARKET_OVERVIEW、APP_RELEASE、COMPANY_SYNC，核验Git/远端/worktree/status/diff。工作区P:/project/swhy/Delta1/company-apps-worktree，统一codex/company-apps；本轮基线365fe84，最终提交看Git/远端和交付回复。

## 可复制接续提示词

请继续Delta1公司看板。实施、必要测试与精确清单提交推送授权持续。先审查现有改动，保留其他工作/四提示词，不从旧版重做，不reset/clean/全量stage/强推。

本轮公司包20261110_131148_048_safe_132420_204_4c19bc5e.zip，110109字节，SHAefafad2fbdd5036683a68d1226592dc41a1cbd7e8c006e82f0cfbca413840aa2，9JSON/runtime/Complete=true，HEAD365fe84。13:23开窗与13:24关闭同一App，closed/complete=true，等待空，7.422秒。20.229/76.312秒是开始前旧运行，不混入。Wind已published，12只各60条、共720条，8-10至11-09；最近两期源值相同不等于缺历史。1798/1800报价、四指数覆盖300/50/499/999，214分类仍缺。16个20/60分位均有数值，真实D仍有428条历史零占位，当前D表11-06，不冒报真实覆盖齐备。

用户新五项要求已实现：真实viewport点击四指数，按下/释放及子标签透传；默认300只/15秒、仍5分钟一轮，失败缺项优先、源回包不足下一轮100，不紧密重试；冻结成分快照代次避免读到晚于计算截止的新文件；概览紧凑头部和更大卡内字体（中比例1080p全卡），期货横条加粗内嵌文字；显示层basis_display在配对/派生暂缺时保留上次完整基差/年化/分位和旧F/S/D/T/源时，现价独立更新，raw计算仍如实缺项、不放宽30秒/3秒，不跨slot/到期修订复用，T<5仍排除。

ETF变化表/历史曲线主展示替换为两个规模饼图：同日完整同指数ETF前三+其它；四个实际期货OI手数*价格*乘数（IF/IH300、IC/IM200，源持仓计一次）。优先同步HTTP有效持仓/价，否则同日完成日线；缺档标已知n/4，完整总额留空，不拿成交量/伪0替代，日期/单位/来源明确。旧720条历史/缓存保留，日频有界任务保持。日线准备仅增加当前16合约最新完成日OI真实缺口，先本地、缺才DDB；价格与OI隔离，价格先保存，已有价不冒充OI齐。缺OI旧行可由完整侧缓存整行替换，不混价格/OI修订。不开全体成分日线/研究分钟下载。

最终267项/53.505秒/无跳过/ResourceWarning错误，20项新增加原247项；截图与证据见APP_VALIDATION和忽略的local_artifacts/validation/company_20261110_afternoon。本机模拟不冒公司新图/新交互验收。公司仍用company_retest.cmd自动更新、开窗约10分钟、开窗Overview、提示正常关闭并等排空、关闭后Overview、白名单JSON ZIP。新market_sizes导出各档OI/价/乘数/金额/日期，basis_display导出沿用源。旧包无实际OI值，不能直接复算新饼图金额；新代码待公司反馈点击、字、卡片稳定、300回包、持仓齐备与总额。

逐日实际D及简单年化100*(F-S+D)/S*365/T保持；00/01/02/03每天一条历史收盘，前20/60、排当前日、T<5排除、等值半权。历史确实缺D暂0只写派生，旧日真实D补入重算，今日D不回写过去；当前D不补0，真实冲突/缺价/映射仍阻断。数字不放“估”，假设数量/日期仅悬浮/诊断。32/A02暂停保留，原独立App/Excel及其他回测工作不动。

正确源Y:\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026，业务日B1。现场DisplayRoot\\192.168.91.230\FTPServer仅证据，不猜拼/重映射。旧默认迁移、09:00/15:30有界同步、SourceDirectory/InputFile互斥保持。默认Overview离线，实时VPN手动，DDB仅实际所需价格/OI缺口，不强杀写入者/删锁。

原数据/缓存/配置/凭据/Excel、其他模块/worktree/进程、四受保护提示词、APP_RELEASE.backtest原对象/序列化、七份唯一SHA归档与MANIFEST保留。8453现存原件在本轮前冻结SHA含新ZIP；旧9:24包原路径在本轮前已不存在，absent_before记录，不自行恢复。待办以新交接为准，不把旧提示词/旧包阶段限制覆盖用户新授权。
