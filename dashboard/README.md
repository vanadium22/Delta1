# Delta1 股指期货看板

当前基线：2026-10-19；技术栈 PySide6 / pyqtgraph。唯一日常入口为 `dashboard/start.cmd` 或桌面「Delta1 股指看板」。默认启动实时采集与独立历史维护；先补历史用 `start.cmd --no-realtime`。尚未实现双击后的 VPN 选择向导。

## 文档入口

| 文档 | 用途 |
| --- | --- |
| [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md) | 当前成果、数据口径、验收证据、已知限制与未完成事项 |
| [COMPANY_CHECKLIST.md](COMPANY_CHECKLIST.md) | 公司首次部署、数据包导入、DDB 账号与每天双 VPN 操作清单 |
| [GIT_WORKFLOW.md](GIT_WORKFLOW.md) | 对应分支抓取、更新、推送及前端开发隔离规则 |
| [HISTORY_MAINTENANCE.md](HISTORY_MAINTENANCE.md) | 缺口检测、校验发布、重试、独立维护命令 |
| [NEXT_CHAT_PROMPT.md](NEXT_CHAT_PROMPT.md) | 新对话完整任务 prompt：VPN 向导、IF 分位诊断、两版 App、数字 Excel |
| [CLEANUP_20261019.md](CLEANUP_20261019.md) | 过时文档和测试产物清理范围、归档与保留边界 |
| [data_contract/README.md](data_contract/README.md) | 标准历史数据格式和时间语义 |

## 当前行为

- 页面：行情总览、指标研究、数据管理 / 设置、数据维护。
- 自动查询 IF/IH/IC/IM 挂牌合约，以公司实时接口交叉验证，00—03 连续档位按每日在市合约排序映射。
- 首页年化分位使用连续档位历史；分红取当前具体合约固定情景，缺少新月份时沿用同品种前一到期合约并标注估计。不是逐日真实历史分红。
- 日线和分钟只维护到上海时区上一交易日。独立子进程使用已有 DDB 路由，不登录或切换 VPN；不可达则等待。
- 数据包以新增目录和原子激活方式导入，保留公司原 Wind 数据、旧历史及本机配置。
- 账号由当前 Windows 用户 DPAPI 加密，本机配置、数据、运行证据及密码不进入 Git。

旧 `start_app` / Developer / Viewer / 网页入口已退役。保留的旧发布构建器和计算研究说明仅用于兼容参考，不代表新的展示版、开发版已经完成。新两版 App 与无图 Excel 是下一轮任务。
