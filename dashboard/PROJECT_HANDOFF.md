# 数字 Excel：公司统一分支交接

2026-10-19。后续开发、验证、提交、推送、公司使用统一在 `codex/company-apps`。当前工作目录 `P:/project/swhy/Delta1/company-apps-worktree`；原项目目录仍保留未提交前端和其他工作，禁止强制切换或清理。

历史来源为已发布数字版 `a070339`；本次按依赖逐项选取已提交源码，未整体合并旧模块分支。数字版包含四张无图表工作表、实时可算指标、历史指标和分位样本；09:29前、15:01起和休市时不新接入实时，使用带原时点的历史/保存观测。原有分位 0 保留为合法值，缺失不填 0。IF 原反馈涉及 00/03，诊断工具 percentile_audit.py 保留独立复算能力；本次分支整合不构成新的公司实盘诊断结论。

新增 numeric_config.py：默认复制旧看板配置到 localsetting/numeric_excel，已有副本不覆盖；离线验证标准化历史、合约参考和实时缓存路径。数字服务启动前检查，无历史时明确报缺配置。仅有原始 Wind 数据不等于数字版数据就绪；COMPANY_SETUP.md 提供复用兼容数据或显式增量导入既有独立包的步骤。没有执行公司迁移、未修改公司原 Wind 库，未测试公司 VPN 实连。

公共 instant_dld 仅引入数字后台需要的原始响应保留、合约/档位双身份、OHLC/OI/源时点、实时库 v4 兼容；旧库升级先备份，旧分片保留。保留公司当前 contracts.py 的日历口径和 service.py，以及股指基差实测 CFFEX 修复，未整包覆盖其他模块。

新展示版/开发版及双 VPN 图形向导仍在旧工作目录保留，不在本次公司代码中发布。数字运行无需 Qt，不伪称界面交付完成。实际行情、私有分红、缓存、Excel 成品、凭据均不提交；空白模板为唯一允许的工作簿。

公司按 [COMPANY_SETUP.md](COMPANY_SETUP.md) 顺序操作；运行含义见 [NUMERIC_EXCEL.md](NUMERIC_EXCEL.md)，提交边界见 [GIT_WORKFLOW.md](GIT_WORKFLOW.md)。验证与发布记录以根 COMPANY_SYNC.md 和本机 `.deps/numeric_integration/release.json` 为准。
