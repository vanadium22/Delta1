# 下一对话：公司启动复测与采集说明

2026-11-10。本轮接续c730d46，已验证最新公司包运行b5746c7。用户确认“其余ok”，追加启动提速和目录整理。当前交接见[PROJECT_HANDOFF](../PROJECT_HANDOFF.md)，最终提交看Git/远端。

## 可复制接续提示词

```text
请继续Delta1公司看板。先完整读dashboard/docs/NEXT_COMPANY_RETEST_PROMPT.md，再读根/dashboard AGENTS、PROJECT_HANDOFF、APP_COMPANY_TEST、APP_VALIDATION、APP_MARKET_OVERVIEW、APP_RELEASE、COMPANY_SYNC，核验Git/远端/worktree/diff。

工作区P:/project/swhy/Delta1/company-apps-worktree，统一分支codex/company-apps。已验证20261110_142427_690_safe_143549_135_03c08120.zip，HEAD b5746c7、9JSON/runtime/Complete=true，同一App会话62ac23d34dea43e2834e4b1001f2148b安全关闭6.153秒。16档OI×价格×乘数及四组总额已复算，使用11-09日线，不冒称11-10实时持仓。成分1798/1800、300只/15秒、7批，仍缺两只报价、214行业分类、428历史D零占位。

用户说其余ok，本轮只提速和整理：完整预检/GUI同解释器复用导入；已完整关闭旧会话跳过CIM，未完成写入者仍安全排空。增加startup计时白名单，新增dashboard/常用入口，旧验证产物已核验归档。298项回归通过；本机三次中位3.4736→2.1880秒为隔离空配置启动至首轮结果并安全退出，不当公司实测。267项属于旧b5746c7。

新包优先核验启动时序、首轮结果和同次安全关闭；四指数/中字号/稳定基差/粗条内嵌标签/双饼图保持。JSON没有点击轨迹，用户确认和自动证据分开；未出现basis_display不能说公司包已触发沿用路径。

按源码解释采集：主HTTP3秒；独立成分默认300只/15秒、每轮起点约5分钟，缺项优先/低回包下一轮100。正常App启用后台时，接入时段外仍可60秒一次有限HTTP快照，单独标非实时；默认Overview诊断、只读/暂停不联网。Wind、Y盘09:00/15:30、DDB实际日线价格与16合约OI缺口、昨收/缓存/关闭各自解释，不把15秒一批说成全部股票15秒更新。

实施、必要测试、精确提交推送授权持续。保留原数据/配置/凭据/Excel、四受保护提示词、七份唯一SHA归档、APP_RELEASE.backtest原对象/序列化、其他模块/worktree。逐日D/连续20与60/简单年化及32/A02暂停保持；历史缺D暂0仅派生，当前D不补0，数字不加“估”。实时VPN手动，不强杀/删锁、不重映射Y，不reset/clean/全量stage/强推。
```

## 固定入口

- [常用入口](../常用入口/README.md)：打开看板、公司复测。
- [公司完整操作](../APP_COMPANY_TEST.md)：原company_retest.cmd流程，不另造重复命令。
- [按源码解释采集](../APP_MARKET_OVERVIEW.md#按源码核对的采集流程)、[最终验证](../APP_VALIDATION.md)、[精确发布清单](../APP_RELEASE.json)。

本轮ZIP为114425字节，SHA256=1c17773aa98f36d317a53b466a7be6612b0bab329fea54393f911476c122f4aa。提取/复算证据仅local_artifacts/validation/company_20261110_startup。旧7.422/20.229秒不混入本轮6.153秒；当前D仍11-06，ETF规模12只×60=720条；数值可算不等于真实历史D齐备。

正确源Y:\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026，业务日Sheet1!B1。DisplayRoot为\\192.168.91.230\FTPServer仅作现场映射证据。旧默认运行时迁移、自定义/空白和SourceDirectory/InputFile语义不变。
