# 最新看板交付与 Git 操作

本次唯一支持的入口为 `dashboard/start.cmd`（或 `python -m dashboard`）。
窗口、任务栏和桌面快捷方式使用 `assets/research.ico`。运行 `create_desktop_shortcut.cmd`
可在新机器创建快捷方式；它只移除指向本模块已退役启动脚本的旧链接，备份在 `runtime/retired_shortcuts`。
旧前端源码为历史兼容实现保留，不再作为日常入口。

## 公司电脑安装

1. 获取本分支的完整代码，保留原公司电脑的 `data`、`localsetting` 等本机文件。
2. 在项目根目录安装依赖：`python -m pip install -r dashboard/requirements.txt`。
   如历史任务与 UI 共用环境，再安装 `dashboard/requirements-history.txt`；也可使用独立环境，设置
   `SWHY_HISTORY_PYTHON` 为该环境的 python.exe。UI 环境可通过 `SWHY_DELTA1_PYTHON` 指定。
3. 在关闭看板时安装数据包（下方命令的 `python` 使用 UI 环境）：

   ```powershell
   python -m dashboard.data_package install "完整路径\dashboard-data-20261019.zip" --data-root "公司项目目录\data"
   ```

   安装器先校验 ZIP 内所有文件哈希和路径，再写入 `data/market/index_futures/dashboard/imports/<包标识>`，
   最后发布 `active_package.json`。不删除文件，不写任何 Wind 路径；同包重复导入跳过相同文件，
   碰到原文件内容不同会拒绝，避免覆盖。原有 dashboard 历史目录也保留。
   如手工解压，ZIP 的 `data/` 合并到项目的 `data/`，不能先删公司数据目录；推荐使用上述安装器完成完整性验证。
4. 启动新看板，自动将历史路径和合约参考指向已导入包；原 `native.json` 在本机备份。
   已有有效分红目录优先保留，只有原路径不可用时才使用包内分红快照。公司新分红表应继续更新原目录。
5. 在「数据维护 → 设置历史账号」重新录入该机 DDB 凭据。密文绑定 Windows 机器/用户，不能跨机复制。
   VPN 使用客户端现有登录流程；程序不保存公司 VPN 明文，不自动切换 VPN。

实时 HTTP 快照继续写入原有效 `realtime_root`；原路径不可用时写入当前项目的
`data/market/index_futures/dashboard/realtime`。实时快照不会冒充完整分钟或日线。
日线和分钟维护以自动激活后的 `history_roots` 为准；旧 Wind 数据保留但不会被误当成本批 DDB 补库目录。
完整说明见 [HISTORY_MAINTENANCE.md](HISTORY_MAINTENANCE.md)。

## 本地分支和推送

本次分支：`codex/dashboard-history-release-20261019`。本次只本地提交，**未推送**。
以下在 Git 仓库根目录运行。先用 `git status` 检查并保存自己的改动。

发布者今后确认要远程发布时执行（本文只是操作方法）：

```powershell
git switch codex/dashboard-history-release-20261019
git push -u origin codex/dashboard-history-release-20261019
```

分支已经推到远程后，公司电脑抓取：

```powershell
git fetch origin
git switch --track origin/codex/dashboard-history-release-20261019
# 已建立本地分支时，改为：
git switch codex/dashboard-history-release-20261019
git pull --ff-only origin codex/dashboard-history-release-20261019
```

在尚未推送时，远程没有本分支。可以使用交付的离线 `dashboard-code-20261019.bundle`：

离线包是相对于原工程提交 `003c2e3` 的增量包，公司仓库需已有该提交；`git bundle verify`
会检查前置条件。缺少基础提交时先从现有工程远程抓取基础历史，或在分支正式推送后直接抓取远程。

```powershell
git bundle verify "完整路径\dashboard-code-20261019.bundle"
git fetch "完整路径\dashboard-code-20261019.bundle" codex/dashboard-history-release-20261019:codex/dashboard-history-release-20261019
git switch codex/dashboard-history-release-20261019
```

数据包单独传输，不通过 Git。不要强制添加 `localsetting/`、`.vscode/`、`*.local.*`、
`data/`、`runtime/`、密码、VPN 配置或密文；这些路径均已忽略。
此模块正常运行不读 Z 盘，不要求公共工程旁边存在另一份账号配置或 Python 环境。
