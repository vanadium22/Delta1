# 2026-10-27 公司统一工作区整理

范围仅为 `P:/project/swhy/Delta1/company-apps-worktree`，基线 `638ee82` / `codex/company-apps`。旧工作区、其他 worktree、真实业务数据、配置、凭据及未完成工作保留。本批不改变应用行为；随后看板修复单独提交。

## 已完成分类

- 根 README 改为应用入口和当前说明索引，COMPANY_SYNC 保留当前模块、更新方式和最近发布。
- 看板 README 与 docs/README 集中索引口径、公司测试、交接、历史与冻结 Excel 说明；原 AGENTS、APP_* 和 PROJECT_HANDOFF 路径继续可用。
- 原三份长文完整保存在 docs/archive/2026-10-27/，归档内链接相应调整；精确原文仍可从基线 Git 读取。
- 项目目录分类见 [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)。新增验证输出统一放忽略的 local_artifacts/validation，压缩归档放 local_artifacts/archives，运行依赖继续留在原位置。
- 四份既有 dashboard 未跟踪提示词保留，不改名、不提交。test/ 中独立基差 App 的历史公司诊断也保留。

## 实际归档和清理

按已知旧验证目录白名单、24小时保护期、Git 跟踪及配置引用检查生成明确计划。压缩后逐文件核验 SHA256，并再次核对源文件后才移除旧副本。路径逐级核验在本工作区内；符号链接和重解析点不跟随，不使用递归强删。

| 项目 | 本机结果 |
|---|---:|
| 旧验证产物 | 27,371 文件，966,184,182 字节 |
| 压缩归档 | 270,806,821 字节 |
| 可由已跟踪源码重建的字节码 | 224 文件，4,044,033 字节 |
| 受保护文件核验 | 10,244 文件，427,161,703 字节；无变化、无丢失 |
| 整理前盘点 | 1,422,796,931 字节 |
| 整理后复盘 | 747,989,391 字节 |
| 净减少（含新归档、清单和文档开销） | 674,807,540 字节，约644 MiB |

复盘值为整理完成当次快照，后续验证输出会增加。旧 .deps 从约977 MB降为约11 MB；.deps/dashboard_native 运行依赖、近期验证与 numeric_ui/node_modules 重解析点均保留。dashboard/runtime/distribution 的三个真实数据包、data/qa、日报缓存和独立基差数据未清理。

本机归档：`local_artifacts/archives/validation/20261027-150134-087361a6/validation.zip`。内含原相对路径与 archive_manifest.json；旁边 source_manifest.json、result.json 及 `local_artifacts/LATEST_CLEANUP.json` 提供检索。归档、计划和保护哈希仅留本机，不进入 Git，也不会随公司 git pull 下载或自动执行清理。

六个旧 Git 验证包带 Windows 只读属性，首轮保留；分别复核归档内容及源哈希后只清除这六个已验证文件的只读属性并移除，最终无遗留失败。原仓库 Git 对象未处理。

## 验证与恢复

11项离线维护回归通过，覆盖归档还原、源变化保留、配置新引用、路径越界、依赖保护、重解析点、归档损坏、只读测试包及可重建字节码。原配置的离线 App 预检通过，所有 UI 依赖可导入；无可见窗口、真实接口或 VPN 操作。原桌面快捷方式和源配置哈希不变。

恢复时先把 ZIP 解压到单独空目录，按原路径/哈希清单取所需文件，避免覆盖当前工作；工具与默认只盘点命令见 [tools/README.md](../tools/README.md)。公司只需通常的 git pull 更新文档及工具；本轮未在公司电脑删除任何文件。看板实际接口及持续运行仍按 [APP_COMPANY_TEST.md](../dashboard/APP_COMPANY_TEST.md) 验收。
