# Delta1 券源桌面 App：项目交接与后续修改入口

更新日期：2026-10-15（北京时间）。本文是后续对话的快速上下文，详细操作见 [README.md](README.md)，环境与启动见 [COMPANY_SETUP.md](COMPANY_SETUP.md)。

**代码基线：`a7844a7`，分支 `codex/securities-lending`。** 这是撰写本文时最后一次功能提交；后续请先检查实际 Git 状态，不能回退到本文记录的版本，也不要把历史测试结果当成本次验证。

## 1. 先读这些，避免找错项目

- 这是 **Python + PySide6 原生桌面 App**，默认入口 `python -m securities_lending`。不要改为网页，也不要更换整套技术栈。
- 仓库：[vanadium22/Delta1](https://github.com/vanadium22/Delta1)。代码位于仓库根目录的 `securities_lending/`，并非独立 GitHub 仓库。
- [开发分支内的 App 目录](https://github.com/vanadium22/Delta1/tree/codex/securities-lending/securities_lending)。GitHub 默认页面是 `main`，本次功能没有合并到 `main`。
- 家里实际仓库：`P:\project\swhy\Delta1\project`。
- 公司用户操作目录：`D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard`。先用 `git rev-parse --show-toplevel` 确认根目录，不要因为目录叫 dashboard 就判断为网页项目。
- 公司屏幕是 **1920×1080**，需照顾 Windows 高 DPI、缩窗、数字对齐和列宽。
- 后续优先读：本文件 → README → 适用的 AGENTS.md → Git 状态 → 本次需求涉及的模块和测试。

## 2. 用户已确认的业务规则

### 文件同步与数据时效

1. 每次正式运行按**北京时间运行日期**定位共享根目录下的日期目录。文件结构为：

   ```text
   用户配置的共享根目录/
     YYYY-MM-DD/
       申万内部券单YYYY-MM-DD.xlsx
   ```

2. 默认文件名模板为 `申万内部券单{date}.xlsx`，默认 Sheet 为 **`库存券单`**。日期动态生成，不能写死为参考文件的 2026-10-14。
3. **先完整复制到项目本地，再解析本地 Excel**。校验源与副本大小、复制期间变化及 SHA256；不会拆解、重建或改名工作表。
4. 共享根目录、文件名模板/通配符、Sheet、表头行、具体列名和单位都要可配置。本机真实配置不写进可提交模板或交接文件。
5. 同步失败只能使用符合条件的**同日缓存**，且明确标记缓存及原下载时间；不能用昨日数据冒充今日。
6. 当日没有有效库存、读取失败、没有匹配行是不同状态，不能混同为零库存。下载与读取失败也要能定位本次实际文件。

### 股数、名本与费率

| 项目 | 已确认口径 |
| --- | --- |
| 库存数量 | 每一原始行先取 `min(实际可融股数, 可融股数)`，再按证券汇总；用户说通常较小的是 D 列，但代码应匹配列名，不能固定取 D 列 |
| 原始数量 | 两列均保留和显示；任一必要数量缺失时不能当零，不能确认完整可借上限 |
| 最新库存市值 | 有效库存股数 × 本次有效 Wind 最新价；界面称“库存市值”，与用户目标名本明确区分 |
| 原表金额 | `可融市值`、`可融市值上限` 仅作原始追溯参考，用户认为这些金额不可靠，不参与当前估值/需求计算 |
| 目标名本 | 用户为每只股票独立输入，界面单位为**万元**，内部换算为元 |
| 需求股数 | `floor(目标名本（元） / 最新价 / 100) × 100`，每只股票向下取整至整百股 |
| 可借上限 | `floor(有效库存 / 100) × 100`；需求超过上限必须显示库存不足、原需求及上限，不能悄悄缩减后显示成功 |
| 计算精度 | Excel 数值解析、单位换算、汇总及股数计算使用 Decimal；保留边界精度，例如 0.57 万股 = 5700 股 |
| 价格不可用 | 明确无法估值/计算；不使用旧行情或券单收盘价充当本次最新价格 |
| 费率 | `参考费率` 普通数字 `0.05` 表示 **5%**，不擅自假定年化 |
| 多笔券源 | 可以显示汇总股数，但费率、期限、来源及原始行必须逐笔保留；费率范围不是一个合并成交费率 |
| 来源为“互换” | **自有券源，无需询其他交易台**；仍保留原始来源字符串，不改变库存校验、费率或期限 |

“互换”提示目前只对去掉两端空白后**等于**“互换”的来源生效，其他来源不自动判断归属。汇总股数不意味着已按某个期限、费率或券源分配需求，当前没有自动券源分配功能。

### 默认列映射

`证券代码`、`证券简称`、`实际可融股数`、`可融股数`、`参考费率`、`期限`、`来源`；原始参考字段为 `可融市值`、`可融市值上限`、`收盘价`。默认数量单位股、参考金额单位元、数字费率口径 decimal。完整模板见 [config.example.json](config.example.json)。

## 3. 现在已经实现了什么

- 紧凑原生金融工作台：状态、文件信息、批量输入、股票汇总表、逐笔券源表。
- 单列代码/名称批量查询；Excel 两列“代码/名称 + 目标名本（万元）”粘贴。名称歧义或金额冲突会拒绝应用，避免目标错配。
- 名本逐行编辑；Tab/Enter/上下键移动，Ctrl+Enter 获取价格并计算；也能从当前行粘贴一列金额。修改名本后旧计算失效。
- 选中有库存明细的股票时自动展开下表，分别显示来源、期限、费率、有效库存、两列原始数量、券源说明、文件及 Excel 行号，可收起。
- 汇总行与明细分别支持复制；Excel 导出包含“查询汇总”“券源明细”“数据说明”，另支持 CSV 汇总/明细。互换的自有券源说明也包含在复制和导出中。
- 「计算与追溯」保留价格时间、计算依据和原始文件路径；「文件与同步详情」支持复制全部详情、打开本地 Excel。
- 「打开下载位置」直接到本次下载批次，即使读取失败也可查看；本次没有副本时再打开有效缓存目录。
- 下载、Excel 读取、Wind 请求、导出在后台执行；失败可重试。关闭时等待当前后台任务完成。
- 演示有固定标识，使用合成券单和价格，不访问共享盘或 Wind；演示配置与正式配置完全隔离。

## 4. 最近的问题、修复和用户反馈

### 缺少“库存券单”，只发现 Sheet1

公司反馈的配置是 `*.xlsx*`。在“最新一份（按修改时间）”模式下，它会匹配其他报表。已用合成测试复现：另一份仅含 Sheet1 的文件更新得更晚时会被误选。

用户点击「设置 → 券单来源 → 恢复默认文件名和 Sheet」后，明确反馈**“之后好了”**。因此保留精确文件名与 Sheet 作为默认；不能通过自动改读 Sheet1 掩盖错误。用户的自定义通配符配置仍受支持，但设置页会明确提示误选风险。

旧版读取失败后丢失了下载文件的界面元信息，只打开数据根目录，导致用户看到很多子文件夹且找不到实际 Excel。现已保留失败副本的路径、实际 Sheet、校验信息，并把它与当前有效缓存分别展示。

多层目录是日期/批次快照结构，每个批次内仍有完整 Excel。不要为了简化目录而覆盖历史快照或把失败副本登记为有效库存。

### 提交与同步记录

| 提交 | 内容 |
| --- | --- |
| `a7c0d1c` | 原生 App、Wind 价格、名本换算基线 |
| `f79063f` | 精度、演示配置隔离、默认模板、工作台交互、复制导出及说明 |
| `a7844a7` | 下载失败定位/校验、通配符提示、逐笔券源表、互换来源说明及测试 |

以上功能已推送到 `origin/codex/securities-lending`。用户在公司执行 pull 返回 `Already up to date`；这说明当时没有需要合入的新提交，**不等于 Wind 或所有业务流程已验证通过**，也不能单凭这句判断当前所在分支。

## 5. 改代码时从哪里入手

| 文件 | 职责 |
| --- | --- |
| [desktop.py](desktop.py) | 主窗口、后台任务、状态、汇总/明细表、查询编辑、复制导出入口 |
| [desktop_widgets.py](desktop_widgets.py) / [desktop_theme.py](desktop_theme.py) | 批量输入、键盘编辑、表格控件 / 样式 |
| [desktop_settings.py](desktop_settings.py) | 四页设置、恢复文件默认值、通配符提示、列映射 |
| [service.py](service.py) | 正式/演示隔离、同步与缓存切换、查询聚合、目标校验、合成演示 |
| [sync.py](sync.py) | 日期目录选文件、完整复制、内容校验、批次与缓存清单 |
| [inventory.py](inventory.py) | xlsx/xls 读取、Sheet/表头检查、列映射、Decimal 单位/费率解析 |
| [calculation.py](calculation.py) | Decimal 名本换算、整百股、库存不足/缺失价格等状态 |
| [batch_input.py](batch_input.py) | 批量粘贴解析及冲突检查 |
| [exporting.py](exporting.py) | 汇总/明细导出、复制文本、互换来源说明、精度与公式文本处理 |
| [wind.py](wind.py) / [wind_worker.py](wind_worker.py) | Wind 子进程调用、超时、行业缓存、价格和时间返回 |
| [config.py](config.py) / [config.example.json](config.example.json) | 默认配置、校验、动态北京日期、旧配置迁移 |
| [diagnose.py](diagnose.py) / [resolve_python.cmd](resolve_python.cmd) | 环境诊断 / 启动解释器选择 |
| [tests/](tests/) | 业务、缓存/同步、换算、原生交互、导出和布局回归 |

`server.py` 和 `static/` 是保留的旧网页兼容实现，**当前主入口是 desktop.py**。不要因看到 HTML/JS 就把本任务转成网页开发。仓库内 `index_strategy/`、`dashboard/`、`research/` 等为其他工作，不能顺手修改或提交。

## 6. 环境、缓存与配置边界

- Python 3.13，主要依赖 PySide6-Essentials、openpyxl、xlrd。无需新增依赖来完成当前功能。
- 公司计划解释器：`D:\conda\envs\swhy_delta1\python.exe`；App 支持独立 Wind Python 路径。
- Wind 最新价格为 `wsq` 的 `rt_last`；行业默认申万一级，`industry_sw` / `tradeDate={date};industryType=1`，可配置。
- WindPy 由用户自行在公司管理，**不是普通 pip 依赖**，不要强行安装或反复教用户安装 Wind。
- 家里没有可用 Wind，必须保持演示和模拟测试能力。
- 行业可缓存；最新价每次重新请求，不用旧价格伪装成功。显示的获取时间与 Wind 返回时间不同，RT_LAST 不保证一定为当前时刻的成交。
- 公司早期 Conda 曾卡在 collecting package metadata；后来用户已能操作 App 并反馈恢复文件模板后正常。不要继续假定公司完全无法启动，也不要据此宣称具体解释器环境和 Wind 联调已验证。

```text
securities_lending/
  config.example.json                 可提交默认模板
  config.local.json                   正式本机配置，不提交
  python.local.txt                    本机解释器选择，不提交
  data/
    live/YYYY-MM-DD/snapshots/<ID>/    完整正式 Excel 副本（包括待核查的失败副本）
    live/YYYY-MM-DD/latest.json       最后有效库存批次
    live/YYYY-MM-DD/industries.json   行业缓存
    demo/config.local.json            独立演示配置
    demo/                             演示快照
    demo_source/                      合成演示文件
    exports/                          默认导出目录
```

失败下载元信息与有效库存分开：`state.downloaded_files` / `attempt_downloaded_at` 是本次已复制文件；`state.files` / `downloaded_at` 是当前有效库存或缓存。后续修改不要把两组字段混用。

## 7. 验证记录与尚未验证的事项

- `a7844a7` 完成时，`securities_lending/tests` **72 项测试通过**；这是历史结果，不是未来改动的免测保证。
- 已验证 Decimal 边界、逐笔最小值、缺失数据、动态日期、准确文件选择、复制后读取、源/副本一致性、同日缓存隔离、演示配置隔离、批量冲突、原生键盘/复制/导出、后台响应、明细来源及缩窗布局。
- 参考 Excel 曾只读核对和本地副本解析通过；真实文件及解析数据均未提交。它只确定模板，不能充当未来日期的正式库存。
- 已实际启动 Qt 演示并检查离屏截图，包括模拟 1080p / 150% 缩放（1240×660 逻辑窗口）、读取失败详情和逐笔来源表；这不能代替公司真实显示器检查。
- 公司共享文件读取在恢复默认模板后，**用户反馈恢复正常**；代理没有直接访问公司共享盘做端到端验证。
- **仍需公司验证**：实际 Wind 连接/权限、Python 3.13 兼容性、独立 Wind Python 设置、真实行业字段返回和价格时间，以及网络异常/真实高 DPI 操作体验。
- 不要把终端显示 `(base)`、`git pull` 成功、演示通过视为真实 Wind 联调通过。

## 8. 后续修改与验证流程

1. 先检查适用的 AGENTS.md、`git status --short`、当前分支和最新提交，保留所有已有未提交改动；本文不能覆盖实际代码或用户新要求。
2. 简要指出本次问题和改进，再在现有原生实现上直接修改。普通界面细节自行合理决定，仅业务正确性有实质歧义时提问。
3. 重要逻辑/受影响交互做针对性验证；必要时运行完整 App 测试与演示截图。公司网络和 Wind 无法验证时明确说明。
4. 同步更新 README 与本文件的相关结论；不要永久保留已经被用户新反馈推翻的“待确认”。
5. 需要提交时只暂存本任务明确涉及的代码、测试和说明。不能 `git add .` 混入其他模块，不能提交真实 Excel、缓存、导出、截图或本机配置；不使用 reset/clean/强推覆盖用户工作。

在仓库根目录、正确 Python 环境中：

```powershell
python -B -s -X utf8 -m unittest discover -s securities_lending/tests -q
python -s -X utf8 -m securities_lending --demo --startup-check
python -s -X utf8 -m securities_lending --demo --capture securities_lending/data/demo_preview.png
git diff --check -- securities_lending
```

默认诊断不调用 Wind：`python -s -X utf8 -m securities_lending.diagnose`。只有需要在公司实际检验时，才显式使用 `--wind 000001.SZ`。

公司同步并启动（先检查本地改动，有冲突先保留，不强制覆盖）：

```powershell
Set-Location (git rev-parse --show-toplevel)
git status
git fetch origin
git switch codex/securities-lending
git pull --ff-only origin codex/securities-lending
git log -1 --oneline
.\securities_lending\start.cmd
```

## 9. 可直接用于新对话的开场

> 请先读取仓库 `securities_lending/PROJECT_HANDOFF.md`、README 和适用的 AGENTS.md，核对实际 Git 状态及最新提交，保留未提交修改。此项目是 Python + PySide6 原生桌面券单 App；按交接文档中的已确认业务口径，在现有实现上继续修改。先概括本次问题，再实施、验证并更新说明。不要提交真实券单、本机配置或其他模块改动。我的本次需求是：……
