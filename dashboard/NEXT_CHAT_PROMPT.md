# 继续数字 Excel 工作

先读根 AGENTS.md、COMPANY_SYNC.md、Git操作指南.md，再读本目录 AGENTS.md、PROJECT_HANDOFF.md、COMPANY_SETUP.md、NUMERIC_EXCEL.md 和 GIT_WORKFLOW.md。核对实际 Git 根目录、分支、工作区和远端，不能把待办当完成。

所有 App 统一在 `codex/company-apps`。复用现有 company-apps-worktree，不切换有未提交工作的旧 project 目录。数字版及必要后台可验证后正常提交推送统一分支；新展示版/开发版前端继续不提交、不推送。公司数据、配置、Wind 实测修复、凭据和其他任务修改必须保留。

公司当前需求：已有项目和 Wind 数据，先离线检查兼容历史、复制数字专用配置，再只读缓存打开 Excel，最后在许可时段接公司实时行情。默认用 localsetting/numeric_excel 副本；不得因缺历史直接指向原 Wind SQLite 或覆盖原 data。本机合成测试与公司真实连通验收分别报告。

分位原反馈为 IF00 与 IF03；旧工具可冻结四档复算，新实例与原反馈分开记录。数字 Excel 已有指标，实际时段和旧缓存来源要可辨别。参考本机 release.json 核对本次测试及远端 SHA，不重新推动旧模块发布分支。

后续已加入短文件名写入/打包与显式旧数据迁移，见 SHORT_FILENAMES.md。原本机正式 data 已迁移索引，旧文件保留；七个后台文件同步到旧本机目录，未同步前端或其他任务。精确测试、私有数据包验证、发布 SHA 以 `.deps/numeric_integration/short_release/` 为准。公司需先 pull 再安装新包；不能把用户下载/替换 ZIP 当成已导入，也不能把本机验证当成公司完成。
