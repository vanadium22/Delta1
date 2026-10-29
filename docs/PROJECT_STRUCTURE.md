# 项目目录与文件分类

| 分类 | 路径 | 用途与维护边界 |
|---|---|---|
| 日常应用 | dashboard/、securities_lending/、script_making/、statistics_app/、index_futures_basis/ | 正式源码、原启动入口、各自交接 |
| 基础采集与兼容工具 | index_strategy/ | 历史/实时 SDK 与采集、旧桌面/前端兼容 |
| 公共数据接口 | shared_data/、SHARED_DATA.md | 公共目录、登记、原有复制校验迁移 |
| 配置模板 | config/examples/、模块 *.example.* | 可提交模板；真实配置不放这里 |
| 本机配置与凭据 | localsetting/、模块 *.local.*、环境变量 | 保留原位置与用户保护方式，Git 忽略 |
| 真实行情及业务文件 | data/、模块 data/inputs/materials/cache/ | 原行情、分红、日报、券单和缓存，整理工具不处理 |
| 运行现场与发布数据包 | dashboard/runtime/ | 运行状态、锁、安全接管证据、已有数据包，保留 |
| 运行依赖 | .deps/dashboard_native/、模块自己的依赖目录 | App 运行需要，保留；不与验证产物混放 |
| 自动化测试 | tests/、模块 tests/ | 离线测试源码；测试临时文件放 local_artifacts/validation/ |
| 公司手动诊断历史 | test/ | 独立基差 App 的 Wind 说明和历史回传，不是自动测试目录 |
| 开发维护工具 | tools/ | 默认只生成计划，执行前明确读取该计划 |
| 本机验证与归档 | local_artifacts/ | 验证输出、整理清单、压缩归档和原路径索引，Git 忽略 |
| 当前文档 | 根 README、COMPANY_SYNC、模块 README/PROJECT_HANDOFF | 只放当前入口、边界和最近状态 |
| 历史文档 | docs/archive/ | 原说明及发布长流水，保留历史上下文 |

看板专用说明见[看板文档索引](../dashboard/docs/README.md)。四份既有未跟踪提示词按用户原要求留在 dashboard/，不修改、不混入提交。旧工作区及其他 worktree 不属于本轮整理范围。

新增产物按用途落位：源码进对应模块；可提交模板进 examples；真实文件走既有公共数据接口；离线截图、性能记录和合成输入进 local_artifacts/validation/<任务日期>。旧 .deps 测试目录可以通过[工作区维护工具](../tools/README.md)先核验再归档，不直接清空 .deps。
