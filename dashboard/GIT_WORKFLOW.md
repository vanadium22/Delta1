# 数字版与前端的 Git 交付隔离

仓库 `https://github.com/vanadium22/Delta1.git`，分支 `codex/dashboard-history-release-20261019`。2026-10-19最新授权允许推送数字Excel及必要后台；先前“暂不推送”仅属上一阶段决定。新展示版/开发版前端继续不提交、不推送。

当前执行结果：数字版代码已本地提交 `3a48274`。普通push被自动审批拒绝，尚未推送。随后只读GitHub核对确认该仓库为 **public**，当前连接有push/admin权限；自动审批要求用户明确确认这个具体公开目的地后才可重试。未更换上传途径绕过审批。最终本地文档HEAD和bundle头见 `runtime/release_numeric.json`。

## 提交边界

- 保留共同基线及双VPN维护/诊断提交 `9e91d6e`、文档提交 `a7dcba5`。不回退历史共同界面。
- 本次允许：numeric_excel.py、numeric_snapshot.py、display_state.py、session_clock.py；session_guard.py、native/model.py、native/collection.py 的时段守卫；数字启动/导出cmd、excel_numeric运行脚本和空白template.xlsx、requirements-numeric.txt；必要测试和交接文档。
- 禁止纳入：native/editions_current.py、新两版入口/图标/快捷方式，以及 current.py 中仍未暂存的前端注入增量。其他业务和研究修改不属于此任务。
- `data/`、`runtime/`、`localsetting/`、凭据及DPAPI密文、真实行情/Excel均排除。空白 `dashboard/excel_numeric/template.xlsx` 是唯一允许提交的xlsx；检查无数据行、宏和外部链接。
- 只用文件白名单暂存，不执行 `git add .`、`git add -A`，不使用 skip-worktree 掩盖修改。

隔离验证：从已提交HEAD归档，仅覆盖白名单候选文件，确认没有 editions_current.py、没有 current.py 前端注入；只链接现有第三方依赖。Excel数值刷新与模板验收在独立隐藏Excel实例完成。精确文件哈希/验证记录在本机 `runtime/isolated_numeric`、`runtime/release_numeric.json`，不传业务数据到远程。

## 开发机发布与核验

```powershell
git status
git diff --cached --name-only
git diff --cached --check
# 对照白名单和隔离验证后本地提交；仅正常推送指定分支：
git push -u origin codex/dashboard-history-release-20261019
git rev-parse HEAD
git ls-remote --heads origin codex/dashboard-history-release-20261019
```

以推送成功且远程SHA等于本地HEAD为准。授权本身不等于推送已完成；实际结果和最终SHA记录在本机 release_numeric.json。不同则先核对，不强推或覆盖别人的提交。

## 公司获取

```powershell
git status
git fetch origin
# 尚无同名本地分支：
git switch --track origin/codex/dashboard-history-release-20261019
# 已有同名本地分支：
# git switch codex/dashboard-history-release-20261019
# git pull --ff-only origin codex/dashboard-history-release-20261019
git log -3 --oneline
```

先保留本机数据、配置和未提交代码。快进失败先查分叉，不 reset --hard、不覆盖目录。运行 `dashboard/start_numeric_excel.cmd`；部署及数据包操作见 COMPANY_CHECKLIST.md。

## 离线包

`dashboard-code-20261019.bundle` 按显式分支 `codex/dashboard-history-release-20261019 ^003c2e3` 创建，不使用 `--all`。要求公司仓库已含基础 `003c2e3`。

```powershell
git bundle verify "完整路径\dashboard-code-20261019.bundle"
git fetch "完整路径\dashboard-code-20261019.bundle" codex/dashboard-history-release-20261019:refs/remotes/offline/dashboard-history-release-20261019
# 尚无本地分支：
git switch -c codex/dashboard-history-release-20261019 refs/remotes/offline/dashboard-history-release-20261019
# 已有本地分支则 switch 后 merge --ff-only 上述引用。
```

代码bundle包含数字服务和空白模板，不含新两版前端或业务数据。独立数据zip保持原SHA256 `357977d55f8e4f6e29595fabdd903e0510cf1a67e22a5008d91193cdb8cee695`；不要把公司Wind和凭据加入代码交付。
