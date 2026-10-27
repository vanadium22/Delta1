# 公司统一更新与发布

所有应用、开发与公司运行统一使用 `codex/company-apps`。公司在原 Git 根目录一次 `git pull --ff-only` 更新全部已发布模块；原配置、凭据、数据和未完成工作保持原位。

## 当前模块

| 模块 | 职责 | 交接 |
|---|---|---|
| dashboard | 蓝白市场看板、第六版研究、数据编排；Excel 冻结保留 | [看板交接](dashboard/PROJECT_HANDOFF.md) |
| securities_lending | 券源下载、查询、行业与金额筛选 | [券源交接](securities_lending/PROJECT_HANDOFF.md) |
| script_making | 日报下载、查询、收益与风险邮件产物 | [日报交接](script_making/PROJECT_HANDOFF.md) |
| index_futures_basis | 独立基差、分红、期限结构及报告 | [基差交接](index_futures_basis/PROJECT_HANDOFF.md) |
| index_strategy | 历史 / 实时采集与兼容桌面工具 | [采集接口](index_strategy/instant_dld/README.md) |
| shared_data | 公共目录、数据登记与原有迁移 | [公共数据说明](SHARED_DATA.md) |

## 最近发布

- `638ee82`：根据 overview (3) 修正陈旧当前值的原因传播，明确旧 Wind 记录缺阶段证据，补齐可复制的公司重测步骤。54 项相关回归通过，真实公司 Wind 与运行验收待回传。
- `d2c7299`：安全 Wind 证据、ETF 跟踪字段互补、收盘缓存衔接、真实交易阶段与正式引擎只读预览。186 项相关回归通过。
- `b778c88`：券源工作台行业、库存市值范围及名称/代码组合筛选；129 项券源回归通过。

本轮目录整理只改文档入口、开发维护工具和本机旧验证产物，不改上述应用行为、入口或业务公式。实际文件清单和验证见[整理记录](docs/WORKSPACE_CLEANUP.md)。

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
