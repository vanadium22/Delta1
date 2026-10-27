# Delta1 公司应用与数据工作区

所有模块统一使用 `codex/company-apps`。公司仓库根目录是 `D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard`；各应用、配置与数据并列维护。

## 日常入口

| 用途 | 启动入口 | 当前说明 |
|---|---|---|
| 指数 / ETF / 期指看板 | [dashboard/start_presentation.vbs](dashboard/start_presentation.vbs) | [展示版说明](dashboard/README.md) · [公司测试步骤](dashboard/APP_COMPANY_TEST.md) |
| 券源工作台 | [securities_lending/start.cmd](securities_lending/start.cmd) | [使用与筛选](securities_lending/README.md) |
| 日报下载、查询及邮件产物 | [script_making/start.cmd](script_making/start.cmd) | [日报说明](script_making/README.md) |
| 独立股指基差报告 | [index_futures_basis/start.cmd](index_futures_basis/start.cmd) | [基差口径与报告](index_futures_basis/README.md) |
| 指数策略采集 / 历史工具 | [index_strategy/start_app.cmd](index_strategy/start_app.cmd) | [工具说明](index_strategy/desktop/README.md) |

公司日常更新：正常关闭本次要更新的应用，在原 Git 根目录运行一次：

```powershell
Set-Location -LiteralPath 'D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard'
git pull --ff-only
```

随后使用原入口。更新源码不会自动升级已经打开的旧进程。已有环境继续复用，配置、数据与凭据保持原位。

## 文档与文件分类

- [项目目录索引](docs/PROJECT_STRUCTURE.md)：正式应用、共享组件、配置、数据、测试和历史材料。
- [统一分支与当前发布](COMPANY_SYNC.md) · [Git 操作指南](Git操作指南.md) · [开发约定](AGENTS.md)。
- [公共数据说明](SHARED_DATA.md)：原行情、分红、日报、券源、缓存及迁移接口。
- [看板文档索引](dashboard/docs/README.md)：当前数据口径、公司测试、验证、交接与冻结 Excel。
- [工作区整理记录](docs/WORKSPACE_CLEANUP.md) · [维护工具](tools/README.md)。

`test/` 保留独立基差 App 的公司 Wind 诊断说明与历史回传；`tests/` 是自动化测试。展示版看板的新 Wind 分阶段测试以 [APP_COMPANY_TEST.md](dashboard/APP_COMPANY_TEST.md) 为准。

本机配置、真实数据、输入、缓存、导出、原材料不进入 Git。`.deps/` 保留运行依赖；新验证产物统一存放在忽略的 `local_artifacts/validation/`，历史验证归档存放在 `local_artifacts/archives/`。

## 历史记录

此前根说明和发布长流水已归档，原业务口径和历史材料保留：[原根说明](docs/archive/2026-10-27/ROOT_README.md) · [历史发布记录](docs/archive/2026-10-27/COMPANY_SYNC_HISTORY.md)。当前状态优先读取本页、模块 README 与 PROJECT_HANDOFF。
