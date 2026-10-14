# Delta1 券源工作台 · 原生桌面 App

PySide6 原生 Windows 桌面窗口，直接读取本机券单并通过 Python `WindPy` 获取行情。默认启动不打开浏览器、不启动 HTTP 服务。每次启动先从共享目录复制**北京时间运行日**券单，读取 `库存券单` Sheet，支持批量查询库存、名义本金、费率、行业及 Wind 最新价，为每只票输入目标名本后校验股数。

## 公司机器首次使用

1. 将本分支同步到公司机器，进入 `securities_lending` 文件夹。需要 **Python 3.10+**，不需要 Node.js。
2. 配置专属 Conda 环境，详见 [公司环境配置](COMPANY_SETUP.md)。默认路径 `D:\conda\envs\swhy_delta1`。已有环境时双击 `install.cmd` 仅安装/更新本 App 依赖，不另建 `.venv`，不安装 WindPy。
3. 双击 `start.cmd` 打开原生桌面窗口；`start_demo.cmd` 打开合成演示。正常 Windows 启动使用 `pythonw.exe`，没有常驻控制台；错误记录在 `data/startup.log`。
4. 第一次打开「数据与环境设置」，粘贴公司的「发送券单」文件夹路径。也可以粘贴某一天的完整目录，运行时自动替换日期。保存后立刻同步，之后每次启动自动同步。
5. 输入如 `600519 300750.SZ 平安银行`，点击「查询库存与最新价」。空格、逗号、分号可分隔，最多 100 个输入。名称支持包含匹配，结果按证券代码去重汇总。
6. 在每只票的绿色输入框填写**目标名本（万元）**，点击「刷新价格并计算」。每次计算重新向 Wind 请求价格；改动名本后旧的换算结果立即失效。

可直接使用公司已安装 WindPy 的 Python：

```powershell
$env:D1_LENDING_PYTHON = 'C:\path\to\wind-python\python.exe'
.\start.cmd
```

也支持已有项目变量 `SWHY_DELTA1_PYTHON`，或在「数据与环境设置 → Wind 与环境」单独设置 `wind_python`。该项留空时使用 App 同一环境下的 `python.exe`，不通过基础环境中转。公司机器应先登录 Wind 终端，由你在终端中安装/修复对应环境的 Python API；不从公共 pip 安装同名包。

演示模式包含合成库存与价格，不访问公司共享目录、不调用 Wind、不改写正式配置。界面、CSV 和缓存目录明确区分演示/正式模式，关闭窗口即可退出。源码方式运行，尚未打包成脱离 Python 的单文件 EXE。

从仓库根目录也可启动：

```powershell
python -m pip install -r securities_lending/requirements.txt
python -X utf8 -m securities_lending
python -X utf8 -m securities_lending --demo
```

## 名义本金换算

用户确认采用 **每只票 100 股向下取整**，规则固定：

```text
需求股数 = floor(目标名本（元） / 最新价 / 100) × 100
最大可借 = floor(券单同一标的合计数量 / 100) × 100
取整名本 = 需求股数 × 最新价
未用名本 = 目标名本 − 取整名本
```

使用 Decimal 计算，避免二进制浮点误差把刚好一手的金额算少。需求超过最大可借时，明确显示「库存不足：需要 X 股，目前最多可借 Y 股」，不会自动把超额需求当作通过。低于 100 股对应名本时提示最低金额；数量缺失/部分缺失时不确认库存上限；价格缺失、非正数、异常时不换算。

最大可借是**当前已加载券单**下的上限，原始数量中不足 100 股的部分不计入。缓存库存、下载时间、原始逐笔费率与文件行号可在窗口查看；程序不预留券源或发送交易指令。不同费率/期限仍保留逐笔明细。

## 数据处理规则

- 日期固定采用北京时间。默认读取 `共享根目录/YYYY-MM-DD/`，也支持路径中显式包含 `{date}`。不自动找上一个交易日，节假日没有当日文件时明确显示未就绪。
- 默认从 `*.xls*` 中筛选 `.xlsx/.xlsm/.xls`，忽略 Excel 锁文件 `~$*`，读取修改时间最新的一份。多个文件如果是同一库存不同版本，保持此选项；如为不同券源，改为「合并全部」。可用文件名通配符缩小范围。
- 合并模式会忽略 SHA256 完全相同的文件，其他文件/行均累计。同一库存不同版本即便仅改变格式也可能被重复累计，因此合并前应确认它们是独立券源。
- **只读取指定库存 Sheet**，扫描前 50 行自动识别表头；支持指定 Excel 表头行号及列名映射。多列存在歧义会报错，避免静默取错列。
- 名本按**名义本金**处理。优先使用券单原始名本列；缺失且券单有价格时，以 `可融数量 × 券单价格` 估算，界面/导出明确标注。没有价格时保留缺失，不调用实时价格自行替代。
- 数量统一到股，名本统一到元，界面汇总显示万股/万元。优先识别单元格显式单位，其次表头中的股/万股、元/万元/亿元；无单位时使用设置中的口径。
- Excel 百分比格式（例如底层值 `0.025`）和带 `%` 的文本会自动识别。普通数字默认 `2.5 → 2.5%`；如果原表用 `0.025 → 2.5%`，在设置中选择小数口径。费率显示遵循券单，**不会擅自假定或换算年化口径**。
- 同一标的多条记录合计数量及名本，显示费率范围；展开查看每条原始费率、期限、文件与 Excel 行号。不将不同期限/费率取简单平均。
- 无库存匹配、数量为零、字段缺失分别显示。缺失字段不当作零库存；汇总注明仅包含已知值。公式无缓存值时提示用 Excel 重算保存，程序不执行宏或公式。
- 支持沪/深/北交易所 6 位证券代码，包括数字单元格前导零修复、`600519.SH`、`SH600519`。纯 6 位码按交易所前缀规则推断；存在市场歧义时请在券单及输入使用完整带后缀代码。其他市场代码需扩展解析器。

## Wind 最新价与行业

最新价和行业在同一个隐藏 Python 工作进程中请求，界面保持响应。最新价采用 `WSQ / RT_LAST`，每次查询或计算都会重新取数，不以券单价格、前收盘价或本地旧行情替代。行业优先使用券单已有信息，缺失时用 WSS 补充。默认请求：

```python
w.start(waitTime=10, showmenu=False)
w.wsq('600519.SH,000001.SZ', 'rt_last')
w.wss('600519.SH,000001.SZ', 'industry_sw', 'tradeDate=运行日YYYYMMDD;industryType=1')
```

行业字段、参数和页面口径标签均可配置，默认标签为「申万一级」。公司终端的字段可用性、行业版本、授权范围需在 **Wind 代码生成器**中确认。ETF 等标的可能没有相应行业，保持待补充。API 连接方式参考 [Wind 官方 Python 封装](https://github.com/WindQuant/Official/blob/master/WAPIWrapper/WAPIWrapperPython/WindPy.py) 和 [Wind Client API](https://www.wind.com.cn/portal/zh/ClientApi/index.html)。

默认 Wind 总超时 25 秒，行业失败不会丢掉已成功返回的最新价。价格失败则保留库存查询、清空旧价格和换算结果，修复环境后再次查询/计算即可重试。行业按日期和字段参数缓存，价格不缓存复用。界面显示本机获取时间与 Wind 返回时间；WSQ 返回时间不等于逐笔成交时间，盘后/停牌时 RT_LAST 可能是最近成交价。

## 配置与本地文件

`config.example.json` 是可提交模板。App 保存到 Git 忽略的 `config.local.json`；真实公司共享路径和 `python.local.txt` 本机解释器设置不进入 Git。支持的 `columns` 键：

```json
{
  "code": "证券代码",
  "name": "证券名称",
  "quantity": "可融数量（万股）",
  "nominal": "名本（万元）",
  "rate": "出借费率",
  "industry": "所属行业",
  "price": "参考价",
  "term": "期限"
}
```

```text
securities_lending/
  config.local.json                 # 本机私有配置（忽略）
  data/                            # 所有券单/运行数据（忽略）
    live/YYYY-MM-DD/
      snapshots/<批次ID>/          # 从共享盘实际复制的 Excel
      latest.json                  # 最后成功批次、来源、大小及 SHA256
      industries.json              # 当日 Wind 行业缓存
    demo/                          # 演示缓存，与正式缓存隔离
    demo_source/                   # 自动生成的合成 Excel
  desktop.py / desktop_*.py         # 原生 Qt 窗口与设置
  calculation.py                   # 名本、100 股取整、库存校验
  wind.py / wind_worker.py          # 独立 Wind Python 工作进程
  environment.yml                  # 公司专属环境定义（不含 WindPy）
  tests/                           # Excel、Wind 模拟、换算、原生交互测试
  start.cmd / start_demo.cmd
```

每次成功同步都保留独立批次，不覆盖已成功的券单。源文件复制过程中变化会中止本次导入。下载和解析全部成功后才切换当前快照；失败可回退同日、同来源、同文件筛选与读取模式的已校验缓存，页面明确显示「使用当日本地缓存」。不会使用昨日文件冒充今日数据。历史批次保留供追溯，需要时可手动清理旧日期目录。

App 保持打开跨日时会清空旧结果并重新同步，每次查询也检查日期。日内共享目录更新后点击「同步当日券单」重新读取。CSV 使用原生保存对话框选择位置，默认在项目 `data` 目录。

旧网页代码保留供兼容排查，默认 App 不调用它。仅显式执行 `python -m securities_lending.server` 才会启动旧本机 HTTP 界面；本次新增的逐票名本输入与换算在原生 App 中提供。

## 同步与测试

在公司已有 Delta1 仓库中：

```powershell
git fetch origin
git switch -c codex/securities-lending --track origin/codex/securities-lending
```

分支已存在时，切到该分支后 `git pull --ff-only`。若公司当前分支有其他修改，可创建独立目录避免干扰：

```powershell
git worktree add ..\Delta1-lending origin/codex/securities-lending
```

自动验证（仓库根目录）：

```powershell
python -X utf8 -m unittest discover -s securities_lending/tests -v
```

覆盖动态日期、前导零、表头/列名、单位与费率、多笔合计、公式缺失、当天缓存与跨日隔离、Wind 响应/部分失败/无旧价回退、Decimal 取整边界、库存不足、原生窗口录入/查询/计算/导出与配置校验。测试只生成合成数据，不连接真实 Wind。

本机无法访问公司共享目录或 Wind。实际券单列名、真实费率口径、Wind 行业字段与授权需要公司联调。出现解析问题时，可提供去敏后的表头、数值格式、页面解析提示；不要上传完整真实券单到公开 Git 仓库。
