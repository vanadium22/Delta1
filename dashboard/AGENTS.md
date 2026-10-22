# 数字 Excel 公司交付

遵循根目录 AGENTS.md：统一使用 `codex/company-apps`。数字版日常只使用本文件夹的 `start_numeric_excel.cmd`，简短步骤在同目录打开方式.md，部署按 COMPANY_SETUP.md；不再在Git根目录另建数字Excel入口。解释器顺序为显式SWHY_DELTA1_PYTHON、公司实际存在的D:/conda/envs/swhy_delta1/python.exe、仓库.venvs/numeric_excel、仓库.venv、本机实际存在的P:/code_content/python_work_env/conda_env/swhy_delta1/python.exe，最后PATH。公司原有 Wind 环境、数据和本机设置必须保留。

本目录在统一分支只发布数字 Excel、空白模板及必要计算/数据后台。native 目录中的模块为无 Qt 的计算依赖；不表示已发布看板界面。新展示版、开发版、前端入口/图标/快捷方式及其未提交改动仍留在旧工作目录，不复制、不暂存、不推送。

默认数字配置为 `localsetting/numeric_excel/native.json`，首次从既有 `localsetting/native.json` 复制；已有副本不覆盖。不自动迁移 Wind 库，不把供应商原始库当标准化 Parquet 数据集，不从开发机复制公司凭据。

仅 `excel_numeric/template.xlsx` 可提交 Excel 文件，必须保持无实际行情、宏或外链。真实数据、每日缓存、导出、runtime、localsetting 均不提交。公共 realtime_store 改动必须验证旧库只读保持、备份迁移、旧分片不变及采集回归；不连真实公司接口来跑自动测试。
