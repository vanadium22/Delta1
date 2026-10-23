# 公司展示版交付范围

统一使用 codex/company-apps，远端 https://github.com/vanadium22/Delta1.git。用户授权本轮验证通过的源码、测试与说明提交推送。2026-10-23 授权覆盖旧“仅 Excel、App 前端不发布”限制。

公司只交付展示版入口和必要 UI/共享数据后台；开发类窗口保留为共享实现和本机同步依赖，开发入口只在原本机目录。范围见 APP_RELEASE.json。保留旧工作区其他未完成工作，逐文件同步需要的修复，不全量覆盖。

所有真实行情、分红、配置、凭据、DPAPI、诊断日志、成品、缓存与下载均不提交。本轮不改 Excel 界面/模板/工作簿。使用明确文件白名单，不 git add . / -A，不 reset/clean、强推或强制切换。

发布前：核对源码/Git差异、离屏窗口及后台回归、原配置保护和暂存差异。提交后 git push origin codex/company-apps，再用 git ls-remote --heads origin codex/company-apps 核验与 HEAD 相同。公司盘中测试单独标待验，不把模拟请求算公司通过。

旧离线 bundle 和私有数据包原样保留。日常以一次 git pull --ff-only 更新，不需重导数据。
