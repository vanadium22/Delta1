# 公司电脑部署与每日操作清单

更新日期：2026-10-19（Asia/Shanghai）。共同入口现在已有双VPN启动向导。新展示版/开发版暂不提交，因此不包含在公司离线代码bundle中。

## 1. 导入共同代码

- [ ] 正常关闭旧看板并等待任务退出；备份公司data、dashboard/localsetting、业务分红Excel及未提交代码。
- [ ] `git status` 核对修改。不要清理工作区、强制重置、覆盖整目录。
- [ ] 按 [GIT_WORKFLOW.md](GIT_WORKFLOW.md) 获取指定远程分支，或验证并导入最新 `dashboard-code-20261019.bundle`。先核对远程 SHA / bundle 头，不以旧离线包替代新数字版。
- [ ] 核对分支 `codex/dashboard-history-release-20261019` 和交付文档记录的维护提交。

## 2. 环境和独立数据包

已有可用环境不必重建。新环境安装：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r dashboard/requirements.txt
.\.venv\Scripts\python.exe -m pip install -r dashboard/requirements-history.txt
```

- [ ] 修正本机 `history_python`、`SWHY_HISTORY_PYTHON` 或 `SWHY_DELTA1_PYTHON`，不照抄开发机绝对路径。
- [ ] 数据包单独传输，不包含在Git或bundle。现有包SHA256为 `357977d55f8e4f6e29595fabdd903e0510cf1a67e22a5008d91193cdb8cee695`，本轮未改动。

```powershell
.\.venv\Scripts\python.exe -m dashboard.data_package install "数据包完整路径\dashboard-data-20261019.zip" --data-root ".\data"
```

- [ ] 安装器先验证整包，再增量写入 `imports/<包标识>`，最后切换激活标记。保留公司Wind原文件、历史和配置，不进行镜像覆盖。
- [ ] 重复安装相同文件跳过，冲突拒绝覆盖；不要通过删除公司文件绕过。
- [ ] 首次打开自动采用包内路径并备份原native.json，保留有效业务分红目录。

## 3. 每日双VPN向导

1. 双击 `dashboard/start.cmd` 或原“Delta1 股指看板”快捷方式。
2. 选择“检查并补齐历史”“跳过，使用现有历史”或“取消”。选择前没有持续采集。
3. 需要补库时，在客户端登录DDB VPN后点击确认。无凭据时在向导的数据维护页“设置历史账号”录入数据库配置；不会要求在聊天或命令行提供密码。
4. 观察目标日期、剩余缺口、下载/校验/发布、滞后和重试时间。已有完整数据不重复下载。可重试或“停止补库并继续”。
5. 等待程序显示“历史进程已退出”。暂停或complete状态文字不能替代此步骤；程序会回收子进程后才继续。
6. 按提示断开DDB VPN、登录公司VPN，点击“已切换，验证连接”。通过一次有限查询后才开启实时。
7. 失败可重试或离线进入。离线窗口点击“开始实时”会再次验证；陈旧报价不伪装实时，历史分位保持原定位日期和有效n。

`start.cmd --no-realtime` 仍显示向导，但验证后不自动开始持续采集。需要重新补库时正常关闭窗口，再从向导进入；运行中的维护页不会直接连接DDB。独立维护命令与实时进程互斥，繁忙时保留数据并拒绝第二任务。

## 4. 凭据、异常与验收

- [ ] VPN由用户在客户端操作，程序不自动登录、切换、退出或保存VPN密码。
- [ ] 数据库凭据使用当前Windows用户DPAPI加密；新机器重新录入。密文不能作为跨机配置复制。
- [ ] 无网络、SDK或凭据时，保留已发布历史；缺必要输入仅使相关指标缺失，不填0或清空全部指标。
- [ ] 源滞后按现有退避重试；来源冲突默认阻止覆盖，人工复核后才能明确采用仅补缺失键的策略。
- [ ] 观察四品种具体合约、分红继承、报价源时、分位定位日期、有效n和数据质量；HTTP连接成功不等于报价新鲜。
- [ ] 重复双击激活已有向导/窗口。激活失败不会悄悄另开采集实例。
- [ ] 安装包和提交不含localsetting、DPAPI密文、真实历史、实时库或其他业务模块本机修改。

本轮程序关闭顺序和异常路径已有测试；实际切换VPN的端到端验收仍需在客户端完成。公司Wind保留以增量安装规则和安装回归为依据，本轮没有改动公司原文件。

## 5. 数字 Excel 与本地前端

数字版现单独交付：安装桌面 Microsoft Excel，复用 Python 环境或安装 `dashboard/requirements-numeric.txt`，运行 `dashboard/start_numeric_excel.cmd`。运行端不需要 Node、artifact-tool、VBA。关闭该工作簿停止刷新；直接打开 xlsx 查看最后保存值。只读共享缓存可加 `-ReadOnlyCache`。具体命令和指标说明见 [NUMERIC_EXCEL.md](NUMERIC_EXCEL.md)。

09:29前、15:01起及休市日默认不接入实时；展示最新历史或最后有效保存行情。逐行数据时点与缓存标记必须保留，缓存不保证是收盘最终价。日线/OI指标不会因为刷新按钮而变成实时指标。每日计算缓存和实际Excel成品留在 `data/cache/dashboard/numeric`。

新展示版/开发版仍只在开发机本地：展示版增加六项常用指标，但界面文件、入口、图标及 `current.py` 前端接入增量不进入Git或公司bundle。远程只含空白Excel模板、数字服务和必要公共后台，真实数据另行增量迁移，保留公司Wind文件和凭据保护。
