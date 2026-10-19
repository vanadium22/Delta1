# 公司电脑历史数据维护

## 使用方式

双击 `start.cmd` 或新桌面快捷方式「Delta1 股指看板」。最新研究界面自动启动实时采集和历史维护子进程。
需要先补历史时，运行 `start.cmd --no-realtime`，补齐后切回公司 VPN，再点「开始实时」。
打开「数据维护」查看等待原因、补库进度和剩余缺口。原来的 Developer / Viewer / 网页启动脚本与快捷方式已退役。
「暂停历史维护」只暂停历史下载，暂停状态跨重启保存；「立即检查 / 重试」恢复并忽略本轮冷却时间。

历史下载不操作任何 VPN。两套 VPN 是否能共存取决于公司的客户端限制和路由配置；
本机实测公司 VPN 在线时 DDB 隧道配置失败；断开后 DDB VPN 可登录且数据库可下载，因此使用互斥切换流程，不能承诺共存。
即使历史数据库网络恢复，任务也只借用已有路由，不拥有或退出 VPN。
若公司环境必须切换 VPN，可在使用实时行情之前手动准备好 DDB 网络，执行一次补库命令，
结束后再切到实时网络；或者在独立机器/时段运行同一程序。程序不会替用户执行这些切换。

## 公司电脑配置

1. 单独分支包含 `dashboard`、`index_strategy/history` 和实时查询依赖，不要求另一份公共工程或 Z 盘。
   安装 `dashboard/requirements.txt`；DDB SDK 可放独立环境（`dashboard/requirements-history.txt`）。
2. 按 [交付与 Git 操作](DEPLOYMENT.md) 安装数据包；首启自动调整本机读取路径，保留公司配置和 Wind 文件。
   实际读取历史是 `history_roots` 中的目录，目前为 `normalized/backfilled_cn_index` 与
   `normalized/backfilled_cn_index_future`；不要只更新旧的 `normalized/cn_index*`。
3. 若解释器位置不同，设置 `native.json.history_python` 或环境变量 `SWHY_HISTORY_PYTHON`。
   可选 `history_connection_file` 指向本机 DDB 配置；已有公共配置继续使用，否则采用 `dashboard/localsetting/ddb.connection.local.json`。
4. 在「数据维护 → 设置历史账号」输入公司电脑的地址、端口、账号、密码。配置使用 Windows
   当前用户 DPAPI 加密，并限制文件 ACL 为所有者和 SYSTEM。原电脑密文不能在另一电脑/账号使用。
   密码不通过命令行、请求文件、状态页面、日志或导出传递。错误只记录固定原因/异常类别。
5. VPN 在正常客户端交互登录，不要求复制本机 VPN 配置。DDB 命令行安全录入（此命令只配置，不登录）：

   ```powershell
   python -m index_strategy.history.protected_config --config dashboard/localsetting/ddb.connection.local.json --kind ddb
   ```

   密码通过隐藏输入读取。已有明文配置可加 `--migrate` 转换并回读校验；本机现有配置已迁移。
   VPN 的精确网关证书校验保持启用。VS Code 不能直接使用 DPAPI 配置，其原重复明文字段已清空；
   对应加密备份在该工具 `.vscode/connection-0.credentials.local.json`，需要扩展时自行交互登录，勿恢复明文自动保存。

所有本机配置、加密凭据、原始运行日志均不打包；数据仅用专用白名单导出，另行交付，不提交 Git。当前 Git 忽略规则覆盖
`localsetting/`、`.vscode/`、`*.local.*`、`data/`、`dashboard/runtime/`。
现有对外看板打包器使用源文件白名单，不含这些配置或数据目录。

## 独立运行 / Windows 计划任务

`dashboard/maintain_history.cmd` 运行一个有界批次，最多查询 80 个代码/频率/日任务，
查询阶段最多约 120 秒（单次 SDK 超时除外）；首轮磁盘核验单独计时。
每次最多到运行当天的上一交易日，不因晚间运行而下载当天。
退出码 0 表示完整，2 表示仍有缺口/等待，3 表示被同目录锁或本地 I/O 阻止，4 表示启动配置错误。

如自行设置 Windows 任务计划程序，可使用历史解释器，参数：

```text
-B -s -X utf8 -m dashboard.marketdata.history_maintenance --once --local-root <公司项目目录>\dashboard\localsetting
```

起始目录设为 `<公司项目目录>`，以录入凭据的同一 Windows 用户运行。
建议每 5 分钟调度；程序内部保留退避时间和逐任务冷却，不反复请求同一滞后日期。
本次没有自动安装操作系统计划任务。UI 与外部任务使用相同目录锁；关闭 UI 只停止其自己的子进程。
`history_maintenance_enabled=false` 可关闭 UI 自动任务，独立命令仍可使用。

## 维护范围、校验与故障恢复

- 默认从已存在的最早日线起，四个指数和所有已知挂牌合约，分别检查日线与每个应有分钟点。
  `history_start` 可指定更早起点；该区间必须有可验证的官方日历和合约参考。
- 2025/2026 休市安排独立于 DDB，来源分别为
  [2025 上交所年度公告](https://www.sse.com.cn/disclosure/announcement/general/c/c_20241223_10767108.shtml) 和
  [2026 上交所年度公告](https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml)。
  后续年度从官方 HTTPS 公告列表发现、解析、缓存原文及哈希；未知格式或年份不可用时等待，绝不猜测。
  新合约上市前和旧合约到期后不产生补库任务。合约参考不足时先提示更新合约。
- 合约换月与实时交叉验证沿用现有实现；分红仍按具体合约。缺新合约分红沿用同品种前一到期合约，
  例如 2706 沿用 2703，表内真实数据出现后优先使用，包括实际零值。
- `_maintenance/<标识>/status.json` 是汇总状态，`pending.json` 保存完整缺口和逐代码覆盖，
  `jobs.json` 保存尝试次数及重试时间，`coverage_cache.json` 是可重建核验缓存。
  `downloads/` 保留 DDB 原始规范化批次和校验清单。所有路径均在实际历史数据旁，不依赖 Z。
- 校验失败/价格冲突 24 小时冷却并展示原因，人工重试可提前检查；不自动修改原价格。
  网络/源库滞后以 5、15、30 分钟退避，其他未尝试任务先继续；登录失败需人工更新后再试。
- 已核验来源差异并决定保留原值时，可以显式运行
  `python -m dashboard.marketdata.history_maintenance --once --force --preserve-existing`。
  此选项只对此次命令生效，默认自动任务仍严格拦截冲突。它只插入不存在的时间键，
  不更改已有有效值，并将差异字段、样例、缺失时间点和保留策略写入 `quality_notes.json` 与不可变版本。
  时间点完整不等于不同来源完全一致；「数据维护」页持续显示差异数量，数据包会携带这些说明。
- 单个批次全部暂存并回读校验后，用一个 `publication.json` 发布指数和期货的版本组合。
  当前/上一代文件不可变，读者可继续持有旧快照。中途崩溃的暂存文件不生效；再次启动重新核验补缺。
  外部程序绕过联合发布写同目录时，自动任务发现版本分歧会停下，不能擅自覆盖。

## 实际仍需外部维护的内容

DDB 源库的及时性和 VPN 连通性由公司提供，程序只能显示等待与重试，不能从不存在的源数据生成行情。
分红预测 Excel 的更新仍需业务提供；这次没有自动生成分红预测。
历史来源更正仍需要人工核验后显式增加修订版本，避免不同来源的价格冲突被自动覆盖。
不可变版本与下载证据目前保留，不自动删历史；长期运行应按公司的留存要求另定清理策略。
