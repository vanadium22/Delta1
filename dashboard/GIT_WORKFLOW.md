# 数字 Excel 交付隔离

遵循根目录 AGENTS.md：公司所有 App 统一使用 `codex/company-apps`。仓库为 `https://github.com/vanadium22/Delta1.git`（公开）。用户已授权验证通过的代码、测试及说明推送该统一分支；后续不再更新或推送模块分支。

早前数字版本发布于独立看板分支，其提交 `a070339` 仅作为本次选取已提交源码的历史来源。不要再让公司切换那个分支；不整体合并其历史，不覆盖公司最新 CFFEX/Wind 修复。现有旧工作目录的未提交前端、其他任务修改、数据和配置保持原样。

## 本次边界

- 允许：数字服务/启动器、独立配置检查、空白 Excel 模板、数据与指标计算依赖、时段和缓存守卫、必要公共实时库兼容代码、针对性测试和说明。
- 暂不发布：current.py、native/app.py、native/editions_current.py、static 网页、展示/开发版入口、图标及快捷方式。native 目录内发布的是计算后台，无 Qt 前端。
- 不发布：公司 Wind/HTTP/DDB 实际数据、真实 Excel 成品、私有分红、缓存、配置、凭据、DPAPI 文件、其他任务修改。唯一允许的 xlsx 为无行情行/宏/外链的 `excel_numeric/template.xlsx`。
- 只用明确文件白名单暂存；不全量 add，不通过 skip-worktree 隐藏差异，不强推、不清理或强制切换旧工作目录。

## 核验与发布

先核验统一分支与远端关系、模板无数据、后台测试及实际 Excel 连续更新；审查暂存文件清单和差异，验证未改基差 Wind/其他 App。提交后正常推送：

```powershell
git push origin codex/company-apps
git rev-parse HEAD
git ls-remote --heads origin codex/company-apps
```

远端 SHA 与本地 HEAD 相同才算发布完成。测试和远端核对记录保存于被忽略的 `.deps/numeric_integration/`；本模块交接和根 COMPANY_SYNC.md 记载结果。公司更新见 [COMPANY_SETUP.md](COMPANY_SETUP.md)，不把“已获授权”写成“已推送”。

## 离线代码

新离线 bundle 命名为 `company-apps-numeric-20261019.bundle`，仅包含本次统一分支代码增量，以 `f8c1d2f` 为前提提交。保存在本机 `dashboard/runtime/distribution/`，不上传业务数据。公司默认在线 pull，无需反复导入 bundle。

旧数据 zip 保留为独立私有数据交付，不加入 Git 或公开 bundle。安装需显式使用 dashboard 专属增量安装器，不解压覆盖公司 data。

2026-10-19 短文件名后续交付：新增 `company-apps-shortfiles-20261019.bundle`，仍以 `f8c1d2f` 为前提，包含数字版接入及本次后台修复。新数据 ZIP `dashboard-data-short-v2-20261019.zip` 单独私有交付，不加入 bundle/Git。公司步骤见 SHORT_FILENAMES.md。当前真实发布 SHA 与包校验记录见本机 `.deps/numeric_integration/short_release/`。
