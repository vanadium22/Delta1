# Delta1 公司看板当前交接

2026-11-10。本轮基线1b621fc18ee433db8ab593b325d79e2b7872755a，统一分支codex/company-apps；批次2026-11-10-company-display-resilience-and-final-retest。最终提交看Git/远端及交付回复，精确清单见APP_RELEASE.latest_update.files。必要实施、测试和精确清单提交推送授权持续。

## 本轮实现

- ETF卡减少文字，以价格、折溢价和规模/占比/买卖价差数字为重点。无盘中值时保留带日收盘溢价，只有准确前一交易日才称昨日，不将NAV冒充IOPV。
- 用户授权补历史规模。现有WindPy netasset_total（或已配置规模字段），unit=1/Fill=Blank/Days=Trading，每组当前前三只单独读取近三个月；代码/字段/日期/矩阵校验，每日NAV任务一起有界更新。失败保留历史，缺值不前填/不补0，单只坏历史隔离。图改为近三个月规模（亿元），表比较相邻两次有效规模及日期，只有一期不伪造0，真实相等才0。规模变化含净值涨跌，不叫份额/净申赎。占比保留原完整同日全集分母及基准日，不混新单只规模与旧分母。
- 行业剔除缺报价/昨收/权重，篮子涨跌=sum(w*r)/sum(w)，贡献点=指数昨收*sum(w*r)/10000，维持原指数权重、不放大已覆盖部分。旧权重带原日期，不能伪称准确昨日；部分行业按实际覆盖贡献参与排名，待分类单列。右条绑定涨跌%而非贡献点。资料SHA仅因NAV变化不再清空同代码报价。
- 成分独立HTTP每100只/15秒、约5分钟一轮，每批raw/SQLite提交后立即发布快照；昨收用HTTP yesterdayClosePrice，不每轮去DDB取1850只。360秒预算仅用于滚动成分；主报价3秒及期现30秒/3秒不变。App默认不补全部成分日线/锚点，显式overview_stock_daily_enabled仍支持旧完整模式，不改个人配置。
- 显示结果按indices/etfs/quotes持续原子保存到LocalRoot/overview_display。缺整组保留上次结果及原源时，新有效部分优先，新价格不套旧基差，缓存恢复不变实时；离线Overview可读不写。
- App成分日常不自动逐股Parquet导出，raw/SQLite每批已持久化。旧归档及显式有界归档器保留。关闭仍等请求/计算/写入安全排空，不强杀、不删锁。
- 顶部大/中/小页面比例，默认中在1080p及125%系统缩放对应逻辑尺寸全卡可见，大可滚动、小更紧凑。只适配可见页；偏好独立overview_ui.json，不改native.json。期货成交条/图例按真实slot同色，增加色块和引导线。

## 本地验证与公司复测

最终本地测试/截图见[APP_VALIDATION](APP_VALIDATION.md)。模拟源、离屏和本机性能不当作公司Wind/页面/新关闭耗时验收。

运行[company_retest.cmd](company_retest.cmd)：ff-only更新、记录新HEAD/Y映射，开窗约10分钟→开窗Overview→提示用户正常关闭→等排空→关闭后离线Overview→白名单JSON ZIP。完整手动/按需分红/行业ETF命令统一见[APP_COMPANY_TEST](APP_COMPANY_TEST.md)。实时VPN手动，Wind保持登录；无同一运行开窗及最终安全关闭则包明确缺项，不压缩LocalRoot/native.json或原始业务目录。

待公司最后反馈：Wind实际三个月规模覆盖/前期日期，行业覆盖/条形和轮询，1080p中比例，缓存恢复及正常关闭耗时。研究32/A02暂停保留，当前年化/逐日D/连续20与60分位保持。

## 已核验的公司事实（旧代码12f34f1）

包20261110_092411_072_safe_094017_545_23667ca4.zip：201,026字节，SHA827b9a1feddd74a88873071b5a0f6ab2a06cc1bd118cf0a06e82abb13d5acc4b；33份JSON、full/Complete=true、无缺项，git及8个diagnosis一致。Y三表B1=10-27/10-30/11-06，库64条/4版本含09-18；Import新增0/unchanged4表示已在库，未见11-09/10新表。16当前D均为11-06表SHA09c72b6a56b57a5e18b2f40a91ecf0d54e2341f0f483900d9961f2500d8f62b2，实际合约全对应；9:36实时F/S/D/T复算最大误差8.8818e-16个百分点。用户随后表示可能比较旧表，不盲改公式/映射。

旧20日16档完整，60日只缺D428条，缺价/映射0。1b621fc已按用户要求历史缺D暂0、补旧日真实D按版本重算；今日新D不回填过去，当前D不补0、真实冲突/缺价/映射阻断。数值不放“估”，补零数量/日期仅悬浮/诊断，真实覆盖独立审计。新分位/显示仍待公司新包。

同次9:36开窗→9:40最终closed/shutdown.complete=true，关闭73.499秒；51.639秒时逐股归档1408/1802，最后空归档0.09秒不是总关闭时间。本轮新性能仍待现场。名单300/50/500/1000，214未分类，权重IF11-02/其余10-30。收盘NAV/价格已证，IOPV/份额/PCF缺定义。

## 路径与保护

已确认Y:\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026，业务日B1。现场DisplayRoot为\\192.168.91.230\FTPServer，仅证据，不重映射/猜拼。旧默认迁移、自定义/空白保留、09:00/15:30有界同步及SourceDirectory/InputFile互斥语义保持。

本机P:/project/swhy/Delta1/company-apps-worktree；公司Git根D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard，LocalRoot其下dashboard/localsetting/app。默认Overview离线，实时VPN手动，DDB只补实际所需价格缺口。原数据/配置/凭据/Excel、四受保护提示词、其他模块/worktree/进程不动；不reset/clean/全量stage/强推。APP_RELEASE.backtest原值及原序列化块保留。

8,453个文件、365,738,904字节编辑前冻结SHA；本轮证据在忽略的local_artifacts/validation/company_resilience_20261110，旧包在company_20261110。七份旧说明与MANIFEST唯一SHA归档不动。先读[接续提示词](docs/NEXT_COMPANY_RETEST_PROMPT.md)，核验最新Git和最终测试，不沿用旧230项结果。
