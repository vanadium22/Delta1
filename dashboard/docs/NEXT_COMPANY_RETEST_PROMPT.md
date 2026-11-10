# 下一对话：公司最终显示与关闭复测

2026-11-10。先完整读本页，再读根/dashboard AGENTS、PROJECT_HANDOFF、APP_COMPANY_TEST、APP_VALIDATION、APP_MARKET_OVERVIEW、APP_RELEASE、COMPANY_SYNC，核验Git/远端/worktree/status/diff。工作区P:/project/swhy/Delta1/company-apps-worktree，统一分支codex/company-apps，本轮基线1b621fc，最终提交看Git/远端和交付回复；不能拿旧230项结果当本轮最终结果。

## 可复制接续提示词

请继续Delta1公司最终反馈核验。必要实施、测试、精确清单提交推送授权持续。先审查已有补丁，保留其他工作和四受保护提示词；不从旧版本重做，不reset/clean/全量stage/强推。研究32/A02继续暂停保留，原行情/分红/缓存/配置/凭据/Excel、其他模块/worktree和进程不动。

本轮已实现：ETF数字重点，现有Wind netasset_total（或已配置字段）unit=1/Fill=Blank/Days=Trading按每组当前前三单只读取近三个月规模，每日NAV任务一起有界更新，失败保留历史，缺值不前填/不补0。图改三个月规模（亿元），表用相邻两次有效规模及日期，只有一期明确缺项、真实相等才0；变化含净值涨跌，不叫份额/净申赎。规模占比仍用原完整同日全集分母，另带占比基准日；IOPV/份额/PCF仍缺可靠定义。原archive读取有界，私有只读SDK可取消，发布者安全排空。

行业按用户要求剔除缺报价/昨收/权重，篮子=sum(w*r)/sum(w)，贡献点=指数昨收*sum(w*r)/10000，保留原指数权重和日期，不整体放大已覆盖部分。旧/部分权重也算已有贡献，不能伪称准确昨日；部分行业按真实覆盖参与排名，未分类单列。右条使用涨跌%而非点贡献，NAV导致参考SHA变化不清空同代码报价。

成分独立HTTP每100只/15秒、约5分钟一轮，360秒预算只用于滚动成分，主行情3秒/期现30秒与3秒不变。个股昨收来自HTTP yesterdayClosePrice，不每轮去DDB取1850只。App默认不补全成分日线/锚点，显式overview_stock_daily_enabled保留旧完整模式。每批raw/SQLite已提交后立即发布最新快照；日常不再周期/关闭自动导出逐股Parquet，旧归档/显式有界归档器保留。

显示按indices/etfs/quotes持续原子保存到LocalRoot/overview_display，缺整组保留上次结果和原时点，新有效部分优先，当前新价不套旧基差；离线Overview可读不写，不能当实时。新增大/中/小页面比例，默认中在1080p及125%系统缩放对应逻辑尺寸全卡可见，大可滚动、小更紧凑；偏好独立overview_ui.json，不改native配置。期货成交条/图例按实际slot同色、色块和引导线。

company_retest.cmd一键ff-only更新→记录本轮HEAD/映射→正常开窗约10分钟→开窗Overview→提示正常关闭并等排空→关闭后离线Overview→白名单JSON ZIP。完整手动/按需分红/行业ETF命令仍在APP_COMPANY_TEST。最终本地测试/截图见APP_VALIDATION，不冒公司验收。新包要核验HEAD、同次开窗/closed和耗时、规模历史来源/数量/首尾日期、行业覆盖/轮询和显示比例；缺项包不宣称通过。

当前年化100*(F-S+D)/S*365/T保持；00/01/02/03每天一条历史收盘，前20/60窗口排当前日、T<5排除、等值半权。历史确实缺D暂0仅写派生、不写原库伪0；补旧日真实D后重算，今日D不回填过去。当前D不补0、真实冲突/缺价/映射仍阻断。数值无“估”，假设数量/日期仅悬浮/诊断；最新/实际分红来源日保留。

旧公司包20261110_092411_072_safe_094017_545_23667ca4.zip为33JSON/full/Complete=true，HEAD12f34f1。Y三表B1=10-27/10-30/11-06；64条/4版本含09-18，Import新增0/unchanged4为已在库。最新D11-06、16合约均对应SHA09c72b6a56b57a5e18b2f40a91ecf0d54e2341f0f483900d9961f2500d8f62b2；实时F/S/D/T复算一致。用户可能比较旧表，不盲改公式/映射。旧20日16档完整，60日仅缺D428条，价格/映射0；1b621fc的新占位/ETF及本轮改动仍待新公司包。旧同次安全关闭73.499秒，最后空归档0.09秒不是总耗时。214未分类、旧权重日期原样注明。

正确源Y:\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026，年份目录/文件名不决定业务日，B1决定。现场DisplayRoot为\\192.168.91.230\FTPServer仅证据，不猜拼/重映射。旧默认运行时迁移、09:00/15:30有界同步及SourceDirectory/InputFile语义保持。默认Overview离线，实时VPN手动，DDB仅实际缺口，不强杀写入者、不删锁。APP_RELEASE.backtest原字段/序列化块、七份旧说明和MANIFEST唯一SHA归档不动。证据在忽略的local_artifacts/validation/company_resilience_20261110。
