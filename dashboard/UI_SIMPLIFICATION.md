# Excel 与两版 App 的简化交互（2026-10-22）

本轮调整选择、布局和信息层次，继续使用已发布的注册表、代表选择与计算服务。未新增指标族或改写公式。旧工作区的两版 App 仅本地保留，公司分支仅发布数字 Excel、必要共享选择逻辑、测试和说明。

## 常用操作

1. 打开“期现”“同品种跨期”或“跨品种”。
2. 选择中文指标和输入 X：期货收盘价 close、分红调整基差（bp）、分红调整基差年化。
3. 查看当前选择的代表结果：期现四品种各一主力、跨期四个代表对、跨品种六组代表对。源时、单位、有效 n 和数据状态随结果一起显示。
4. 需要完整实体、子输出、图表、公式或诊断时，再打开详情和高级筛选。

输入改变会保持指标族并请求该输入的独立稳定变体。加载前清空旧值，旧请求结果不能填进新标题。无匹配输入显示不适用；不会沿用旧值或回退到目录第一项。数据不全的代表仍显示并说明原因，不以换腿或填零掩盖缺失。

跨品种不提供期货原始点差，因为不同指数的点位不能直接相减。成交量、OI、成交金额、成本带、ETF、盘口等使用其固定经济定义，标为固定口径，不复制成三份输入变体。B07 在期现只适用真实期货价格，其余适用性继续由原注册表控制。

“期货收盘价 close”对应完整日终序列；选择盘中优先时，界面另行标示最新价/盘中估算和实际源时。没有有效盘中输入则明确展示日终参考，历史日线不冒充当日收盘。年化继续使用逐日实际 T，T<5 留空。

## Excel

继续用本文件夹的 `start_numeric_excel.cmd`。研究页 B3 选择中文指标，E3 选择输入 X，B4 选择时点，E4 选择观察范围。输入中的“更多口径”连接详情页的原始/对数独立口径选择。

首屏仅显示当前结果，导航链接通往对应详情页和指标目录。历史日期、品种、具体腿、期限、分页和参与比例 p 放在详情页的高级区域；p 默认空，显式 0 保留。完整目录、子输出、版本和各腿源时仍可访问，技术编号移入详情。概览中的对应指数名称、代码、价格、源时及原生图表保留。

这些是无宏 Excel 的普通下拉框和工作表导航，结果由原 COM 循环读选择、发请求和回填。维护程序更新同一工作簿，不反复切换活动表或滚动位置。直接重开已保存 xlsx 只是快照；要重新计算，使用原启动器。空白 `excel_numeric/template.xlsx` 不含真实行情、宏或外链。

旧 B3 的稳定变体编号及独立偏好继续兼容；旧关注合约保留，`research_watchlist.json` 不重写。原数据路径、配置、Wind 环境和 VPN 不变。

## 本地两版 App

旧工作目录中的 `dashboard/start_presentation.cmd` 和 `dashboard/start_development.cmd` 分别打开展示版与开发版。研究页使用同一个组件和共享选择映射。常用选择与当前代表在主界面；完整目录、筛选、公式、图表和诊断通过展开区访问。开发版的数据管理、设置和维护页保留。

搜索和筛选若排除了当前项，会清空对应结果；快速切换按请求身份拒绝过期结果。完整指标及原始、对数口径没有删除。输入选择不改变代表的 T−1 决策规则、固定合约历史或固定集合身份。

## 验证与边界

本次冻结输入沿用 `tests/indicator_frozen_fixture.py`，不连接公司接口。新增 `tests/test_indicator_ui.py` 核验全目录中文选择可达、同族切换、固定口径、不适用状态、旧选择迁移、保留关注合约，以及主输入与原计算服务的完整实体契约一致。已有公式及数据边界回归继续沿用。

接手时的 Git、保护文件和改造前画面记录在本机忽略目录 `.deps/ui_simplification/`。用户后续要求不弹窗、不打断其他工作，因此后续验收使用后台 Excel COM 与两版真实 Qt 入口的离屏窗口，不自动打开成品。后台实际选择读取/同工作簿回填、离屏交互和渲染视觉证据分别记录，不将它们称为可见桌面验收。

本轮验证结果：

- Excel 隐藏 COM 完成 42 次实际控制读取与同工作簿回填检查；原 CMD 入口完成两次隐藏更新，原缺值、合法 0、原生图表检查通过。
- 两版 App 分别通过 48 个主组合、682 条指标完整契约及投影比对，合计 96 个组合、1364 条结果。另覆盖原始/对数、固定口径、不适用、快速切换与旧请求拒绝、搜索、p 空/0/0.1、分页和偏好恢复。
- 实际 Qt 窗口离屏渲染检查 1920×1080、1180×800 以及小窗展开详情；Excel 首屏、年化单位与详情已检查。截图均为冻结合成输入，不是真实行情。
- 新选择映射 10 项、原工作区逻辑 20 项及相关既有回归通过。两目录 10 个共享模块哈希一致，原数据、缓存、配置及其他任务的已有修改保护核验通过。
- 空白模板含 16 张工作表、15 个内部导航链接及原生图表，无真实行情、宏或外链；原图表缺值辅助公式的预期 `#N/A` 保留。

详细本机证据：`app/acceptance.json`、`app/visual_review.json`、`app/visual_details_review.json`、`excel/latest_com.json`、`excel/latest_launcher.json`、`template_release_check.json`、`audit/protection_check.json` 和 `release.json`，均位于上述忽略目录。

公司真实融资/成本、ETF/IOPV、分红、分钟、OI 完整性、历史可见性认证与长期实时运行仍待公司环境验收。本次不下载、补采、搬迁或重建数据，不修改原本机配置。公司更新仍为在原 Git 根目录执行 `git pull --ff-only origin codex/company-apps`，然后使用原启动器。

## 开发机重建空白模板

公司日常运行不需要此步骤。开发机使用已有 Artifact Tool 环境和原 `build_template.mjs`；元数据仅来自共享注册表，不读取行情或本机配置。在仓库根目录执行：

```powershell
New-Item -ItemType Directory -Path .deps -Force | Out-Null
python -c "import json; from pathlib import Path; from dashboard.numeric_excel import HEADERS; from dashboard.numeric_view import METRICS; from dashboard.indicator_catalog import catalog,PAGES; from dashboard.indicator_ui import ui_controls; Path('.deps/template_metadata.json').write_text(json.dumps(dict(headers=HEADERS,metrics=METRICS,catalog=catalog(),ui_controls={p:ui_controls(p) for p in PAGES}),ensure_ascii=False),encoding='utf-8')"
node dashboard/excel_numeric/build_template.mjs dashboard/excel_numeric/template.xlsx .deps/template_metadata.json
```

生成器缺少选择元数据时会报错，避免生成空下拉框。内部工作表导航由 `internal_links.py` 写为原生内部链接，无外链或宏。可选冻结输入预览在导出空白模板后填入，仅用于开发验收，不进入发布模板。发布前核验正常 Excel 打开、主结果和数据表无行情、宏/外链为空及原生图表仍存在。
