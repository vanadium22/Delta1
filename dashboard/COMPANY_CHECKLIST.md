# 公司电脑部署与每日操作清单

适用日期：2026-10-19 当前版。双击 VPN 启动向导尚未实现；下述为现在可执行的流程。命令在包含 dashboard、index_strategy 的项目根目录运行。以下假设项目使用 `data` 与 `.venv`；自定义数据根目录时安装器和看板必须使用同一配置。

## 1. 备份和导入代码

- [ ] 关闭旧看板；备份公司 `data`、`dashboard/localsetting`、业务分红 Excel 和未提交代码。保留原目录。
- [ ] `git status` 检查本地修改；不要 `git clean`、强制重置、强制切分支或整目录覆盖。
- [ ] 按 [GIT_WORKFLOW.md](GIT_WORKFLOW.md) 从远程抓取对应分支，或验证并导入离线 bundle。远程推送未成功前不能只靠 pull 获取新成果。
- [ ] 确认使用 `codex/dashboard-history-release-20261019`，包含功能基线 `b518a94` 和后续文档提交。

## 2. Python 环境

已有可用 `.venv` 时不用重建。选择公司允许、支持 PySide6 和 DolphinDB SDK 的 Python 环境。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r dashboard/requirements.txt
.\.venv\Scripts\python.exe -m pip install -r dashboard/requirements-history.txt
```

- [ ] 现有 `history_python` / `SWHY_HISTORY_PYTHON` / `SWHY_DELTA1_PYTHON` 若指向原机器，修正为公司环境，不照抄 P 盘路径。
- [ ] 最新启动脚本优先识别项目 `.venv`；历史与界面可共用环境，也可使用独立的历史解释器。

## 3. 安装数据包：保证 Wind 保留

看板保持关闭，运行：

```powershell
.\.venv\Scripts\python.exe -m dashboard.data_package install "数据包完整路径\dashboard-data-20261019.zip" --data-root ".\data"
```

- [ ] 核对文件 SHA256：`357977d55f8e4f6e29595fabdd903e0510cf1a67e22a5008d91193cdb8cee695`。
- [ ] 不删除、不整体替换 data，不使用镜像同步把公司其他数据删除。
- [ ] 安装器先验证全包，再写 `data/market/index_futures/dashboard/imports/<包标识>`，最后发布激活标记；不会写 Wind 路径，旧历史也保留。
- [ ] 相同包重复安装跳过相同文件；同路径内容冲突拒绝覆盖，不能通过删除公司原文件来绕过。
- [ ] 首次打开自动采用包内历史/参考路径，并备份原 native.json；保留公司配置和已有有效分红目录。公司数据截止 10 月 16 日之后的缺口还需 DDB 补齐。

## 4. DDB 账号与首次补库

- [ ] 在客户端连接 DDB VPN。VPN 账号和 DDB 数据库账号是两个配置，不要混用。
- [ ] 运行下面命令，不启动实时。

```powershell
.\dashboard\start.cmd --no-realtime
```

- [ ] 「数据维护 → 设置历史账号」录入数据库地址、端口、用户名、密码。
- [ ] 凭据在公司当前 Windows 用户下 DPAPI 加密；不要复制原机器密文，不写进命令行、Git、聊天或 Excel。
- [ ] 点击「立即检查 / 重试」，检查“实际读取目录”指向公司安装后的目录。
- [ ] 目标为运行当天上一交易日，即使晚上运行也不下载当天。
- [ ] 等待剩余缺口 0、校验发布完成。首次磁盘全量核验可能较慢。
- [ ] 确认公司业务分红表目录有效；以后继续更新该目录。

创建新版桌面快捷方式：

```powershell
.\dashboard\create_desktop_shortcut.cmd
```

## 5. 每天两套 VPN 互斥时

| 顺序 | 操作 | 检查 |
| --- | --- | --- |
| 1 | 关闭旧看板并等其任务退出，再断开公司 VPN | 实时采集停止 |
| 2 | 登录 DDB VPN；运行 `start.cmd --no-realtime` | 界面打开，不启动实时 |
| 3 | 点击「立即检查 / 重试」 | 解除上次保存的暂停，检查/下载缺口 |
| 4 | 等到校验发布完成 | 目标正确、剩余缺口 0；不能只看“命令结束” |
| 5 | 暂停历史维护，正常关闭窗口并等待任务退出 | 页面暂停标记本身不是 DDB 会话已退出的证明 |
| 6 | 断开 DDB VPN，登录公司内网 VPN | 客户端确认连接成功 |
| 7 | 双击新版「Delta1 股指看板」 | 默认开始实时，历史仍保持暂停 |
| 8 | 查看 HTTP 状态、轮数、行情源时间 | 20 个源标的持续返回；有效历史用于分位 |

次日继续从第 1 步开始；「立即检查 / 重试」会解除持久暂停。

如果先不补库：先连公司 VPN 再打开普通入口。已有历史仍可用；缺少必要输入的相关指标显示缺失原因/NaN，不能把合法数值 0 当成缺失，也不必把全部历史指标强制清空。当前版本尚无启动选择弹窗。

## 6. 异常与独立补库

- 网络或源库滞后：按 5/15/30 分钟退避。急需实时可暂停、关闭等待退出，切公司 VPN 后再开看板；已发布历史保留，缺口以后续补。
- 账号失败：重新设置账号后重试，不把密码复制到日志排查。
- 来源冲突：默认保留原数据并阻止自动冲突发布。人工核验后才能明确选择仅补缺失键；不要把 `--preserve-existing` 作为每日默认参数。
- 不开界面可连接 DDB VPN 后运行 `dashboard/maintain_history.cmd`；每轮有界，最多 80 个任务，查询预算约 120 秒（单请求超时另计）。退出码 0 完整、2 尚缺/等待、3 锁或本地 I/O 阻止、4 启动配置错误。持久暂停会影响独立任务，可先在 UI 解除。
- 程序不切换任何 VPN；自动重试不等于可以绕过网络限制。

## 7. 最终验收

- [ ] Wind 原文件存在，原目录未被覆盖/删除；数据安装范围仅为 dashboard 导入目录及激活标记。
- [ ] 数据维护页显示正确目录、截止日和剩余缺口；来源差异说明可见。
- [ ] 公司 VPN 下实时轮数、时点持续增加；源标的 20 个（别名重复行不计独立标的）。
- [ ] IF/IH/IC/IM 连续年化窗口正常，缺失新合约分红显示沿用前一合约并注明估计。
- [ ] Z 盘不可用也能运行；Git 中没有 data、localsetting、runtime、凭据和机器配置。
