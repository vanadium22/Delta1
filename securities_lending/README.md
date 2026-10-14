# Delta1 券源查询

本机 Python 服务 + 无构建步骤的 HTML/CSS/JavaScript 前端。在公司机器上，每次启动先从共享目录复制**北京时间运行日**券单，读取 `库存券单` Sheet，支持批量证券代码或名称查询可融数量、名本、出借费率和行业。

## 公司机器首次使用

1. 将本分支同步到公司机器，进入 `securities_lending` 文件夹。需要 **Python 3.10+**，不需要 Node.js。
2. 双击 `install.cmd` 安装 Excel 读取依赖。该命令创建本目录 `.venv`，不会修改其他项目的 Python 包。若公司包源受限，可用公司允许的 pip 镜像或离线 wheel 安装 `requirements.txt`。
3. 双击 `start.cmd`。浏览器自动打开 <http://127.0.0.1:8766>。
4. 第一次打开「数据设置」，粘贴公司的「发送券单」文件夹路径。也可以粘贴某一天的完整目录；程序会在每次运行时替换最后一段日期。保存后立刻同步，之后每次启动自动同步。
5. 输入如 `600519 300750.SZ 平安银行`，点击查询。空格、逗号、分号、换行均可分隔；最多 100 个输入。名称支持包含匹配，结果按证券代码去重汇总。

可直接使用公司已安装 WindPy 的 Python：

```powershell
$env:D1_LENDING_PYTHON = 'C:\path\to\wind-python\python.exe'
.\start.cmd
```

或在「数据设置 → 高级配置」单独设置 `wind_python` 为该 Python 的完整路径。主程序的 Excel 读取环境和 Wind 环境可以不同。公司机器应先登录 Wind 终端，并在终端中安装/修复 Python API；**不要从公共 pip 安装来源不明的同名 WindPy 包**。

双击 `start_demo.cmd` 可使用合成券单预览，不访问公司共享目录、不调用 Wind、不改写正式配置。页面、CSV 和缓存目录均明确区分演示/正式模式。关闭命令窗口或按 Ctrl+C 停止服务。

从仓库根目录也可启动：

```powershell
python -m pip install -r securities_lending/requirements.txt
python -X utf8 -m securities_lending
python -X utf8 -m securities_lending --demo --port 8767
```

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

## Wind 行业

优先使用券单已有行业，仅对查询结果中缺失行业的代码补充。默认请求：

```python
w.start(waitTime=10, showmenu=False)
w.wss('600519.SH,000001.SZ', 'industry_sw', 'tradeDate=运行日YYYYMMDD;industryType=1')
```

行业字段、参数和页面口径标签均可配置，默认标签为「申万一级」。公司终端的字段可用性、行业版本、授权范围需在 **Wind 代码生成器**中确认。ETF 等标的可能没有相应行业，保持待补充。API 连接方式参考 [Wind 官方 Python 封装](https://github.com/WindQuant/Official/blob/master/WAPIWrapper/WAPIWrapperPython/WindPy.py) 和 [Wind Client API](https://www.wind.com.cn/portal/zh/ClientApi/index.html)。

Wind 在独立隐藏进程运行，默认总超时 25 秒，不可用时保留库存查询结果并显示具体错误。失败后同一次运行不反复连接，修复环境后点击「同步当日券单」重试。行业只在当天缓存，并按字段/参数隔离。

## 配置与本地文件

`config.example.json` 是可提交的模板。页面保存到 Git 忽略的 `config.local.json`；真实公司共享路径不进入 Git。支持的 `columns` 键：

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
  static/                          # 浏览器界面
  tests/                           # 合成 Excel 与接口自动测试
  start.cmd / start_demo.cmd
```

每次成功同步都保留独立批次，不覆盖已成功的券单。源文件复制过程中变化会中止本次导入。下载和解析全部成功后才切换当前快照；失败可回退同日、同来源、同文件筛选与读取模式的已校验缓存，页面明确显示「使用当日本地缓存」。不会使用昨日文件冒充今日数据。历史批次保留供追溯，需要时可手动清理旧日期目录。

浏览器保持打开跨日时会清空旧结果并重新同步；后端每次查询也检查日期。日内共享目录更新后点击「同步当日券单」重新读取。查询结果 CSV 使用浏览器下载位置，不是原始券单缓存目录。

HTTP 服务仅绑定 `127.0.0.1`，校验 Host/Origin，拒绝跨站修改请求；静态资源全部本地提供，不依赖外部 CDN。不要通过反向代理直接公开这个面向本机的服务。

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

覆盖动态日期、前导零、表头/列名、单位与费率、多笔合计、公式缺失、最新文件、重复文件、当天缓存与跨日隔离、Wind 响应/缓存/超时、HTTP 查询和配置校验。测试只生成临时合成 Excel。

本机无法访问公司共享目录或 Wind。实际券单列名、真实费率口径、Wind 行业字段与授权需要公司联调。出现解析问题时，可提供去敏后的表头、数值格式、页面解析提示；不要上传完整真实券单到公开 Git 仓库。
