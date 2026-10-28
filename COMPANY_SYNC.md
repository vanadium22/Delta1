# 公司统一更新与发布

所有应用、开发与公司运行统一使用 `codex/company-apps`。公司在原 Git 根目录一次 `git pull --ff-only` 更新全部已发布模块；原配置、凭据、数据和未完成工作保持原位。

## 当前模块

| 模块 | 职责 | 交接 |
|---|---|---|
| dashboard | 蓝白市场概览、数据编排；研究页暂停，32项源码及Excel保留 | [看板交接](dashboard/PROJECT_HANDOFF.md) |
| securities_lending | 券源下载、查询、行业与金额筛选 | [券源交接](securities_lending/PROJECT_HANDOFF.md) |
| script_making | 日报下载、查询、收益与风险邮件产物 | [日报交接](script_making/PROJECT_HANDOFF.md) |
| index_futures_basis | 独立基差、分红、期限结构及报告 | [基差交接](index_futures_basis/PROJECT_HANDOFF.md) |
| index_strategy | 历史 / 实时采集与兼容桌面工具 | [采集接口](index_strategy/instant_dld/README.md) |
| shared_data | 公共目录、数据登记与原有迁移 | [公共数据说明](SHARED_DATA.md) |

## 最近发布

- 10月28日日报查询：常用列快捷添加筛选，金额严格大于0.1默认开启、本人开仓筛选可选；标的多值支持空格/分号等分隔、保留代码点号。缺列或同名歧义明确显示不可用。128项日报回归与30项界面复验通过，基于本地2026-10-14历史数据核验；公司实际日报待使用时验证。

- 本批10月28日看板：概览和20/60分位保留，统一分红调整简单年化及前序合约D继承；其他研究页暂停。主报价三秒、取消只读Wind阻塞、名单/权重拆分、日频收盘净值溢价及overview-only日线补齐。Excel16合约对比通过，真实公司效果待验收。

- 本批Wind返回解析：修复标准单日多证券1×N、规范WSET日期/字段、保留安全行日期/权重/形状证据；显式只读阶段可固定已完成日，真实公司资料需重测。
- `c356b65`：统一工作区目录/文档分类与维护工具；本机27,371个旧验证文件已压缩校验归档，净减少约644 MiB，10,244个保护文件哈希无变化。11项维护回归及离线预检通过。

- `638ee82`：根据 overview (3) 修正陈旧当前值的原因传播，明确旧 Wind 记录缺阶段证据，补齐可复制的公司重测步骤。54 项相关回归通过，真实公司 Wind 与运行验收待回传。
- `d2c7299`：安全 Wind 证据、ETF 跟踪字段互补、收盘缓存衔接、真实交易阶段与正式引擎只读预览。186 项相关回归通过。
- `b778c88`：券源工作台行业、库存市值范围及名称/代码组合筛选；129 项券源回归通过。

目录整理已由c356b65单独发布，只改文档入口、开发维护工具和本机旧验证产物。实际文件清单和验证见[整理记录](docs/WORKSPACE_CLEANUP.md)。

## 公司更新

```powershell
Set-Location -LiteralPath 'D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard'
git pull --ff-only
```

关闭并通过原入口重开要更新的应用。看板当前测试见 [APP_COMPANY_TEST.md](dashboard/APP_COMPANY_TEST.md)，无需迁移目录或重装 Wind。Git 出错时保留现场，按 [Git 操作指南](Git操作指南.md) 检查。

## 未来新增项目如何一起同步

在本仓库内建立独立模块，先检查嵌套 Git。维护正式源码、README、AGENTS、PROJECT_HANDOFF、可提交模板和本机忽略规则，原材料、凭据与真实数据只留本机。仍在统一分支按明确清单验证、提交、推送；不新建模块开发分支。项目清单同步更新本页与[目录索引](docs/PROJECT_STRUCTURE.md)。

## 误切开发分支后的恢复

Git 分支影响整个检出，不只影响一个模块。先核对当前目录、分支及未提交工作，再按 [Git 操作指南](Git操作指南.md) 返回适合的统一工作区；不强制切换、reset、clean 或覆盖旧工作。历史工作区及其他 worktree 继续保留。

## 历史发布与验证

完整历史流水保存在[整理前发布归档](docs/archive/2026-10-27/COMPANY_SYNC_HISTORY.md)。旧测试数字、旧分支和旧现场结论属于对应时期，不替代当前交接和公司新回传；精确源码历史以 Git 提交为准。
