# script_making：后续脚本项目

本目录已纳入 Delta1 仓库，和 `index_strategy`、`securities_lending`、`index_futures_basis` 并列。当前处于项目准备阶段，**尚未发布可运行的 App 或命令行入口**。

已有本地材料涉及日报、开平仓模板和参考脚本。此次接入 Git 的内容为项目说明、开发交接和本地文件忽略规则；业务功能按后续需求开发。

## 公司同步

公司固定使用 **`codex/company-apps`**。关闭正在运行的 App，在 PowerShell 执行：

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
git pull --ff-only
```

更新后本项目位于 `dashboard\script_making`。今后发布到公司分支的正式代码、文档和配置模板会随整个项目一起更新，无需重新克隆或为该目录另建 Git 仓库。

## 文件如何安排

| 内容 | 位置与同步方式 |
| --- | --- |
| 项目说明、正式源码、测试、无本机信息的配置模板 | 放在本模块对应目录，验证并提交发布后通过 Git 同步 |
| 原始日报、原始模板、旧参考脚本和本地说明 | 保留在 `materials/`，除 README.md 外由 Git 忽略 |
| 输入、运行数据、输出、缓存 | 放在 `inputs/`、`data/`、`outputs/`、`exports/`、`cache/`，保留在各自电脑 |
| 账号凭据、内网地址、本机路径 | 使用后续实现的本机配置接口或环境变量，不写入提交的源码 |

`materials` 里的旧脚本含硬编码登录信息及本机设置，后续复用时先将配置移出源码，再逐项验证业务。原始材料原样保留；Git 拉取不负责搬运这些本地文件。需要在公司使用时放置到公司的本地材料或配置位置。

## 继续开发

先读 [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md) 和 [AGENTS.md](AGENTS.md)。开发分支为 `codex/script-making`，交付时将本次已验证提交汇总、验证并推送到 `codex/company-apps`，公司仍只执行一次 pull。
