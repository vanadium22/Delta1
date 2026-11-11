# 下一对话：HTTP昨收优先与20/60收盘复测

2026-11-11，本轮基线30937eb，最终发布看Git。先完整读本页，再读根/dashboard AGENTS、PROJECT_HANDOFF、APP_COMPANY_TEST、APP_VALIDATION、APP_MARKET_OVERVIEW、APP_RELEASE、COMPANY_SYNC，核验分支codex/company-apps、远端/worktree/diff。实施、测试及精确提交推送授权持续。

本地日线优先，再用HTTP yesterdayClosePrice补源交易日的准确上一交易日，重新核验缺口后DDB仅补剩余历史收盘及最近完成日OI。HTTP必须带明确且一致的tradeDate/tradingDate/tradingDay、匹配实际securityId，并核验两日挂牌/到期和交易日历；只有时分秒或盘前旧快照不入日线。盘后昨收仍写前一交易日，不写当天；昨结算/当前价/当前OI不代替昨日数据。 420项独立回归通过，117.339秒（含加载），无跳过、ResourceWarning作为错误；原395项重跑，新增25项HTTP昨收、日期/合约/路由与页面缓存回归。

## 下一轮要核验

公司按APP_COMPANY_TEST运行一键更新复测。新按钮“一键补齐收盘”，本地→一批HTTP→重新算缺口→DDB；主报价60秒复用回包、盘前快照复用原请求，只有明确源日期/正确实际身份可入日线。只带HHMMSS的现有源不能保证有认证日期，拒绝时保留缺口，不能冒称已补好。盘后11-11的昨收仍写11-10，不写当天。OHLC/OI不从今天搬到昨天。

收到包先看HEAD/完整性/同次开窗关闭，重点data_gaps.http_previous_close（rejected/cached_closes及源日期/身份）、continuous_annual.daily_missing、futures窗口missing，app_reports.history_update/collection/overview_runtime的HTTP证据，以及data_gaps.ddb.connection/maintenance目标与stage。配置地址不等于本轮连通，原缺口剩余才入DDB；OI缺口不挡分位。复核11-10 F/S及四品种四档20/60，不用Y分红11-06解释缺收盘。

公司真实HTTP是否提供可认证交易日、11-10两腿收盘、全部四档20/60分位和新DDB端点仍待新安全反馈包；不把本地合成测试当公司已补齐。

## 保留事实与约束

本机原DDB配置已是192.168.198.77:8904，原DPAPI/TLS不变；显式App地址优先，地址与凭据引用分离。前序本机3秒TCP超时未查询11-10，不代表公司失败。最近已核验公司包仍b5746c7、9JSON完整、同次关闭6.153秒、16档OI金额来源11-09；1798/1800股票、214分类缺失、428历史D占位及当前D11-06未被本轮测试补齐。

保留原数据/缓存/native配置/凭据/Excel及四受保护提示词、七唯一SHA归档/MANIFEST和APP_RELEASE.backtest原对象/原序列化、其他模块/worktree。8454原件大小/SHA不变。逐日D、00–03连续20/60、简单年化、排当前日/T<5/等值半权保持，历史无D暂0仅派生、当前D不补0；32/A02暂停。默认Overview离线、实时VPN手动，不强杀/删锁、重映射Y或reset/clean/全量stage/强推。公盘Y路径与B1规则继续。
