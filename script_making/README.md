# script_making：D1 日报桌面 App

**开发、更新、提交、推送和公司运行统一使用 `codex/company-apps`**，验证后直接提交推送这一分支。可复制命令见根目录 [Git操作指南](../Git操作指南.md)；持续约定见 [AGENTS.md](AGENTS.md)。

升级公共数据后，关闭 App，在公司统一分支 `git pull --ff-only`，双击仓库根目录 [一键迁移数据.cmd](../一键迁移数据.cmd)。自动复制校验并保留原件，重复运行安全。

公共数据目录与看板分钟历史/实时缓存接口见 [SHARED_DATA.md](../SHARED_DATA.md)。首次升级自动复制旧默认目录的日报及已有 Excel 模板，核验后读取公共目录；原文件保留。原始材料脚本不执行、不迁入正式源码。共享目录同步使用进程锁，正式/离线查询规则不变。

在 PySide6 原生桌面窗口中查询收益互换日报和日报复核表，默认读取「存续合约估值」和「簿记要素」，工作表可切换。另支持盈亏统计、D1策略台日报的独立下载与本地文件管理；这两类新日报的业务处理尚未接入。开平计划记录尚处于方案阶段，交易新增、提交和审批流程留待后续需求。

## 2026-10-21 新增日报下载与工作表读取修复

- 左侧「日报下载」打开独立文件管理窗口，分别查看「盈亏统计」「D1策略台日报」的本地文件、最新日期、最后检查时间和同步结果。两类各有「检查并同步」按钮，可随时再次扫描来源；原收益互换/复核表继续使用主窗口「同步前一交易日」按钮。
- 正常启动自动检查三个来源组，分别在限时子进程中执行；新增两类各限时 120 秒，原日报组仍为 45 秒。任何一组失败不阻塞其他组或本地查询。关闭 App 时等待现有任务完成/超时，`--startup-check` 不访问任何共享来源。
- 新来源默认从既有 `source_root` 中截取 `for_jrcx` 及其之前的服务器前缀，再接 `OTC-Quant/pybct/TZQ/盈亏统计_new` 或 `OTC-Quant/pybct/LH/D1策略台日报/report`。不依赖 Y 盘映射，不把具体服务器地址写入源码。可在「数据与同步」单独配置 `pnl_source`、`strategy_source`；留空即自动推导，填写年度目录会自动取其父目录以兼容跨年。
- 识别 `盈亏统计_YYYY-MM-DD_new_adjust.xlsx` 与 `D1策略台日报_YYYY-MM-DD.xlsx`。检查来源根目录及有效年/月/日分区，兼容文件直接放在根目录、年份目录或日期子目录；不递归扫描无关业务目录。目录日期必须与文件日期一致。
- 首次下载北京时间今日之前 7 个自然日内实际存在的报表，不含当天。后续补齐本地最新成功日期之后的报表及近一周晚补文件；失败日期、清单中缺失/变动的文件持续重试，不因其他日期成功而跳过。上游只生成 T-2 时显示其实际日期，不把它标作 T-1；一周无文件时保留空状态，不擅自扩展首次历史范围。
- 同内容的本地文件经哈希、工作簿和报表日期校验后复用，不重复复制。不同目录同日期异内容、已有同名异内容文件都会提示冲突并保留原件；检查后将冲突本地文件移至其他目录，再手动同步。下载按单文件暂存、校验、原子保存，每个成功文件立即登记；后续失败可继续补齐。
- 盈亏统计使用「累积盈亏统计」B3、策略台日报使用「总表」J5核对报表日期，只读缓存值，不计算公式、不分析盈亏。历史明细中的其他日期不用于判断整份报表日期。
- 新文件保存于 App 实际日报保存目录下的 `downloads/pnl/YYYY-MM-DD` 和 `downloads/strategy/YYYY-MM-DD`，保留原文件名；每类独立 `manifest.json` 记录相对路径、来源、日期、大小、SHA256及检查时间，`status.json` 保留最后结果。沿用现有项目保存位置及本机配置，不迁移或覆盖旧日报。
- 主查询窗口及两个新来源均有「打开保存位置」：有选中文件时在 Windows 资源管理器中定位文件，没有文件时打开保存根目录；目录尚不存在时提示先同步。按钮随实际保存目录变化。
- 修复首列为空时取原始行号失败，风险盈亏统计、风险盈亏统计汇总、DMA盈亏统计可读取；「收益总览」及无法识别表头的非明细表按原单元格网格展示，列名为 Excel 列字母，保留有值行的原始行号，合并区域的内容显示在左上角，不还原 Excel 排版。解析异常与真实权限/文件缺失错误分别提示。

公司关闭 App，在统一分支仓库根目录 `git pull --ff-only` 后重开即可。已有共享来源包含正确服务器前缀时无需新增配置。本机模拟同步与真实本地样例验证已完成；公司共享盘访问、实际发布时点仍需公司网络验证。


## 公司桌面快捷方式（2026-10-16）

公司保持 `codex/company-apps`，在仓库根目录 `git pull --ff-only` 后，双击本目录 **`create_desktop_shortcut.cmd`**。它会在公司当前用户的实际桌面创建 **「Delta1 日报查询」** 快捷方式，并自动使用 `assets/app.ico`，无需手动更换图标。只在需要快捷方式的电脑执行；无需新建 Python 环境或管理员权限。

快捷方式通过 Windows CMD 运行本目录现有的 `start.cmd`，沿用其正式模式及解释器选择。路径取自运行脚本所在目录，没有写死家里或公司的盘符；桌面位置使用 Windows 系统配置，兼容重定向桌面。正常启动后控制台随现有 `start.cmd` 结束，报错仍按原入口显示。

移动项目目录后，从新位置再次运行创建脚本即可更新同名快捷方式。若同名快捷方式属于其他程序，脚本报错并保留它；先自行重命名原快捷方式后再创建。不要把创建脚本单独复制到桌面，也不要删除或移动项目内的 `assets/app.ico`。生成的 `.lnk` 包含该电脑的绝对路径，不通过 Git 分发。

需要把快捷方式先生成到指定文件夹时，可在 CMD 使用：

```bat
create_desktop_shortcut.cmd -OutputDirectory "D:\Shortcuts"
```

`-NoPause` 可用于自动化检查。创建过程只依赖 Windows PowerShell 和 WScript.Shell，不启动 App、不读取业务数据；公司若限制 PowerShell/脚本宿主，需按公司策略处理。本机已验证生成、回读、重复更新、中文及特殊字符路径与模拟 CMD 启动，公司实际桌面及策略尚未实测。

## 启动

需要 Python 3.10+、PySide6-Essentials 和 openpyxl。双击 `start.cmd` 打开独立桌面窗口；关闭窗口退出 App。默认不打开浏览器、不启动 HTTP 服务，也不占用固定端口。关闭时若仍在读取或同步，会等待当前任务结束后自动退出。

沿用其他公司 App 的 `swhy_delta1` 环境；缺少依赖时先运行本目录 `install.cmd`。解释器依次从 `REPORT_APP_PYTHON`、`SWHY_DELTA1_PYTHON`、`python.local.txt`、公司默认 `D:\conda\envs\swhy_delta1\python.exe`、已登记的 `swhy_delta1` 环境及 PATH 查找。`python.local.txt` 写完整路径（一行、不带引号），保留本机。

也可从仓库根目录运行 `python -m script_making`。`start.cmd --startup-check` 在读完本地目录/默认工作表后自动退出，用于检查启动；不触发共享目录同步。日常双击采用 `pythonw.exe`，无持续控制台窗口。读取和筛选在后台线程运行，共享目录复制在有 45 秒超时的独立进程运行。

## 来源路径与保存位置

在「数据与同步」填写共享来源目录和本地保存目录，也可点击「浏览」使用系统文件夹选择器，点击「保存设置」立即生效。共享来源应包含 `YYYY-MM-DD` 子目录，不包含最后一级具体日期。默认保存在仓库根目录的 `data/reports/swap`，配置值 `@shared` 表示公共目录。旧默认 `data/reports` 自动兼容。

- 设置保存在忽略的 `config.local.json`，配置模板见 [config.example.json](config.example.json)。
- `SCRIPT_MAKING_SOURCE` 和 `SCRIPT_MAKING_DATA` 环境变量可覆盖上述目录；覆盖时 App 显示来源并禁止修改对应输入框，移除覆盖后可修改。
- 更换保存目录后读取新目录，原文件仍在旧目录，不自动搬移。
- 每个日期目录的 `manifest.json` 记录来源、时间、大小、相对本地路径和 SHA256；界面和 API 仍返回解析后的完整路径。
- 点击「导入 Excel」通过系统文件选择器导入已有日报，可同时选择两份；文件名必须保留日期和 `-D1` 后缀。

「同步前一交易日」按北京时间选择**早于今日的最新有效日期文件夹**，下载：

正常打开App时自动在后台执行一次上述检查：两份本地报表通过清单哈希及工作表校验则直接复用，缺失则自动下载。手动刷新本地不会重复同步；没有来源配置、断网或下载失败时显示原因，仍可查已有本地报表。`--startup-check`保持不联网。日期仍以共享来源的最新目录为准，依赖上游按交易日生成。

```text
收益互换日报(YYYY-MM-DD)-D1.xlsx
日报复核表(YYYY-MM-DD)-D1.xlsx
```

此规则依赖上游按交易日生成目录，不单独维护交易日历。界面显示实际日期。最新目录缺文件时停止，不静默回退旧日期。网络失败时可继续查询本地数据，访问超过 45 秒停止本次同步。

两份文件先暂存，检查默认工作表、源文件稳定性、大小和 SHA256 后保存。同日期同名但内容不同的已有文件不覆盖，可更换保存目录。重复下载相同文件不重复生成 Excel，并记录共享来源核验。

## 搜索和筛选

- 每个条件按「选择列 → 内容格式 → 条件与数值」操作。格式默认采用列识别结果，可手动选「文本」「数字」「日期」；每个条件独立解释，同一列也可添加不同格式的条件。
- 选择「数字」可对文本保存的金额、含千分位或百分号的值按数字筛选；不能转换为数值的内容与空值不计作零。选择「文本」可对数字编号进行包含或简称搜索。手动日期格式采用 `YYYY-MM-DD`，无效日期不匹配。
- 更换列或内容格式会重置该条件的操作与输入，避免沿用不兼容的条件；不会改写 Excel，也不会改变其他条件的格式。
- 默认「模糊匹配」支持连续子串和顺序简称。例如「申万」「证投」均可匹配「申万宏源证券投资总部」。
- `/`、逗号、竖线分隔可选词（OR），空格分隔同时需要的词（AND）。多个列条件按 AND 组合。
- 可改用连续包含、精确等于、不等于、为空、不为空。
- 数值列提供范围、大小比较、近似等于、近似零和非零。支持科学计数法、千分位和百分号；`5%` 表示原始数值 `0.05`。
- 默认绝对容差 `ε = 1e-8`，窗口中可临时调整，在设置中保存默认值。`|x| ≤ ε` 为近似零，`|x| > ε` 为非零，空值不计作零。
- 范围采用 `min - ε ≤ x ≤ max + ε`；大于为 `x > value + ε`，大于等于为 `x ≥ value - ε`。小于对称处理。
- 日期格式提供日期区间。支持表头排序、分页、显示列和双击查看全部字段详情，详情显示 Excel 原始行号。拖动表头边缘可调列宽。
- Ctrl / Shift 多选当前页记录，Ctrl+C 复制选中行的可见列与列名，复制使用原始值。窗口大小及每个工作表的显示列保存在 `ui.local.ini`。更换筛选、日期、页码或工作表会清除当前表格选择；持久化开平计划尚未实现。
- 读取 Excel 保存的缓存值，不调用 Wind 或重新计算公式。使用原始小数筛选，显示格式不影响比较。

## JSON 接口

接口作为独立兼容入口保留，与桌面 App 共用本机配置与查询逻辑。需要接口时从仓库根目录单独运行 `python -m script_making.app --port 8766`，仅监听本机 `127.0.0.1`。桌面 App 直接调用 Python 服务层，不依赖该 HTTP 进程。默认桌面入口是 `python -m script_making`，不要使用旧的 `--open` 启动方式。

| 方法与路径 | 用途 |
| --- | --- |
| `GET /api/settings` | 读取本机设置及实际保存目录 |
| `POST /api/settings` | 更新 `source_root`、`data_dir`、`epsilon`，立即生效 |
| `GET /api/catalog` | 本地日期、文件、来源、默认工作表 |
| `POST /api/sync` | 请求体 `{}`，开始后台同步 |
| `GET /api/sync` | 查询 `idle/running/success/error` |
| `GET /api/sheets?kind=swap&date=2026-10-14` | 可用工作表 |
| `POST /api/query` | 查询、排序、分页，返回字段类型及 Excel 行号 |
| `POST /api/import` | 二进制 Excel，`X-Filename` 为 URL 编码后的原文件名 |

JSON 请求使用 `Content-Type: application/json`。`kind` 为 `swap` 或 `review`。不传 `sheet` 时使用默认工作表。列 ID 从查询响应的 `columns` 获取，不能依赖任意列名对应固定位置。

```json
{
  "kind": "swap",
  "date": "2026-10-14",
  "sheet": "存续合约估值",
  "filters": [
    {"column": "c2", "value_type": "text", "op": "fuzzy", "value": "证投"},
    {"column": "c14", "value_type": "number", "op": "range", "min": "5000", "max": "10000"}
  ],
  "epsilon": 1e-8,
  "sort": {"column": "c14", "direction": "desc"},
  "page": 1,
  "page_size": 50
}
```

`value_type` 可选 `text/number/date`；省略时采用原识别类型，兼容旧请求。文本操作：`fuzzy/contains/eq/ne/blank/not_blank`。数值：`range/gt/gte/lt/lte/eq/ne/zero/nonzero/blank/not_blank`。日期：`range/eq/gte/lte/blank/not_blank`。`search` 为全字段关键词，每页最多 200 条，最多 30 个条件。错误返回 HTTP 400 和错误信息，跨站访问返回 403。

## 公司更新与验证

公司保持 `codex/company-apps`，关闭 App，在仓库根目录运行：

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
git pull --ff-only
```

然后运行 `script_making\start.cmd` 打开桌面 App。缺少依赖时运行 `script_making\install.cmd`；首次使用需在 App 中配置共享来源。已有 `config.local.json` 和已保存日报直接沿用，本机设置和原始数据不通过 Git 同步。

离线测试（从仓库根目录）：

```powershell
python -m unittest discover -s script_making/tests -v
```

测试使用合成 Excel 和本机临时目录。实际公司共享盘验证状态见 [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md)。

本次桌面实现沿用仓库其他 App 的 Qt Widgets，依赖安装方式可参考 [Qt for Python 官方文档](https://doc.qt.io/qtforpython-6/gettingstarted.html)。

正式源码、测试和无真实数据的配置模板进入 Git。`materials` 原始文件、`data`、`cache`、导出和 `*.local.*` 保留本机。开发与交付遵循 [AGENTS.md](AGENTS.md)。
