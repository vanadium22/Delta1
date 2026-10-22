# Delta1

## 2026-10-22 移除净利润排名图

日报已移除pnl1底部的净利润排名图，现按「全年收益图 → 六行风险汇总 → 各组收益汇总及重点明细」排列。更新只涉及日报仓库，详见 [日报说明](script_making/README.md)。

## 2026-10-22 日报风险汇总位置调整

日报第一张 `pnl1.png` 现按「全年收益图 → 六行风险汇总 → 各组收益汇总及重点明细 → 净利润排名」排列，第二张 `risk.png` 展示四个风险明细表。公司已确认前一版运行成功，本次只需更新日报仓库；详情见 [日报说明](script_making/README.md)。

## 2026-10-22 当前规则：精简盈亏、分日报合计与第三附件

本节覆盖下方历史版本的全量原表、三值卡片、跨日报总汇总及两附件说明。已保存的 Work Automation 任务无需重新创建或保存；入口、现有启停、北京时间09:20目标、批次、去重和FOF保持。

- pnl1只展示本期累计与两期变动，计算仍保留上期；年初至所选日全部历史、T-2、缺日和跨年规则不变。指定台及其后4个原始行置顶（空行不跳过），其他原Excel名称单元格加粗汇总按原序，场外业务合计唯一置底。读取合并锚点、缩进和outline层级，原行号、来源、表头与注释保留。缺缓存不补零。分组不唯一、层级/合并不明确、组和不等于总计等均显示诊断并停止排名；不猜组名单。可靠时在pnl1底部按带符号净利润降序绘制万元排名，突出目标台但保留真实位置。
- risk前4行不变，末2行改为各日报内部两类别的观察项合计，日期各自保留。正文及risk_totals记录同口径；4个明细表追加金额合计，数量列为“—”。空观察子集保留零金额合计，来源失败不能变零。IF/IH/IC/IM.CFE排至对应明细末尾，区段内按所选指标绝对值稳定降序。
- 增加swap_stocks.png普通附件，复用本次收益互换风险快照、阈值和剔除名单，排除指数、期货与ETF；不改变risk股票/其他ETF分组。pnl1/risk保持CID内嵌与纯文本后备。导出仍包含EML、正文、统计记录、邮件设置及export_directory；版本5指纹、完整文件集和哈希包含第三图，旧产物保留。失败/不完整拒绝可发送草稿。
- 工作台仅对适配器做必要修复：遍历嵌套MIME叶节点，核对所有图片字节及哈希；发送队列和已保存任务不变。登录启动按具体原因诊断，SID识别等价用户名、规范路径及解析参数，检查当前解释器、目录、唯一动作、唯一当前用户登录触发器；读取失败与配置不符分别提示。没有注册、删除或启停真实计划。

验证使用隔离目录与合成Excel、模拟计划/SMTP。日报98项回归；工作台132项首轮仅Conda临时文件争用1项失败，受影响测试串行复验见工作台验证记录。跨仓库HTTP/固定解释器/Windows Job至模拟SMTP验收通过，覆盖三图片字节、两CID、普通附件、纯文本、旧邮件兼容、批次/目录复用及0/1/2/3。292份全年历史、长组名、负值和25行股票明细的完整导出已实际查看；离屏QA需显式加载系统微软雅黑（首次未加载的方框图已重新生成检查）。未访问正式共享数据、运行真实日报或发真实邮件。公司真实Excel样式与邮件客户端仍由现有流程验证。

公司空闲时手动完全关闭工作台后更新两处原分支，命令不启动后台：

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\project\work_automation'
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw '工作台更新失败' }
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
git pull --ff-only origin codex/company-apps
if ($LASTEXITCODE -ne 0) { throw '日报更新失败' }
```

更新后由用户按原方式重新打开工作台。登录启动只读诊断和重新应用步骤见工作台docs/STARTUP_DIAGNOSTICS.md；无需另建日报定时器。


**所有 App 的开发、更新、提交、推送和公司运行统一使用 `codex/company-apps` 一个分支。** 这是用户于2026-10-19确认的长期约定，后续不再分模块开发分支。公司名为 `dashboard` 的文件夹本身就是仓库根目录，包含并列的 `index_strategy`、`securities_lending`、`index_futures_basis` 和日报桌面 App `script_making`。用户已于 2026-10-15 确认首次迁移完成，解压包备份已删除。

**复制 Git 命令请打开 [Git操作指南.md](Git操作指南.md)**，包含公司/家里项目路径、pull、按文件提交与push、远端有新提交时的处理。

**公司 Wind 检查请打开 [test/Wind诊断.md](test/Wind诊断.md)**，可直接复制运行诊断和复制结果的 PowerShell 命令。

**数字 Excel 看板请打开 [dashboard/COMPANY_SETUP.md](dashboard/COMPANY_SETUP.md)**：沿用公司统一分支，先检查历史数据和独立配置副本，再打开自动更新的无图表 Excel；新看板前端暂不发布。

以后关闭 App，在 PowerShell 运行以下命令，即可一次更新整个项目中已发布的模块和公共文件：

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
git pull --ff-only
```

公司和家里都在 `codex/company-apps` 开发与更新，验证后直接提交推送这一分支。本机配置、分红 Excel、行情缓存及导出继续保留；历史工作目录中的未完成内容受保护。完整约定及首次迁移历史见 [公司统一同步说明](COMPANY_SYNC.md)，开发交付要求见 [AGENTS.md](AGENTS.md)。

2026-10-16 公共数据升级：基差、日报、券单统一使用仓库根目录的 `data`。本次 pull 后，关闭 App，双击根目录 [一键迁移数据.cmd](一键迁移数据.cmd)，复制校验已有数据并保留原件；再次运行会复用成功记录。公司数据保存在本公司仓库的 `data`，不依赖家里盘符。分钟历史、实时每日缓存及看板读取接口见 [公共数据说明](SHARED_DATA.md)。

若基差目录只剩本地数据文件夹，先检查 `git branch --show-current`：切换 Git 分支会影响整个仓库。误切开发分支时，按 [公司统一同步说明中的恢复步骤](COMPANY_SYNC.md#误切开发分支后的恢复) 切回公司分支即可恢复已跟踪源码。正确模块名为 `index_futures_basis`。

今后要把新项目加入统一更新，只需明确项目目录及本次需求。正式代码、说明和无真实数据的模板完成验证、提交并发布到公司分支后，公司一次 pull 就会取得新增目录及后续改动。新增项目流程和当前清单见 [COMPANY_SYNC.md](COMPANY_SYNC.md#未来新增项目如何一起同步)。[script_making](script_making/README.md) 提供原生桌面日报下载、查询和文本/数字格式筛选，双击 `script_making\start.cmd` 启动；原始日报、Excel 和旧参考脚本保留在本机。

指数策略研究的数据采集项目。Git 仓库根目录是 `project`，实时行情入口位于 `index_strategy/instant_dld`。

## 目录

```text
project/
├── README.md
├── .gitignore
├── config/examples/               # 可提交的配置模板，不含真实账号
├── localsetting/                  # 本机私有配置，Git 忽略
├── index_strategy/
│   ├── env/                       # Conda 环境定义、固定版本依赖和恢复说明
│   ├── desktop/                   # CustomTkinter 原生桌面应用
│   ├── start_app.cmd              # Windows 双击启动桌面应用
│   ├── frontend/                  # 早期网页界面，保留为可选入口
│   ├── instant_dld/
│   │   ├── config/symbols.json     # 维护标的列表，可增加多个 JSON/TXT/LIST 文件
│   │   ├── client.py              # HTTP 请求和业务响应检查
│   │   ├── symbols.py             # 标的读取、合并、校验
│   │   ├── collector.py           # 轮询、重新加载标的、分批及停止
│   │   ├── quotes.py              # 量价、五档盘口、秒级时间与缺失值归一化
│   │   ├── realtime_store.py      # 实时事务库、按标的/年月发布 Parquet
│   │   ├── reader.py              # 策略只读 DataFrame 与独立结果保存
│   │   ├── storage.py             # 旧 JSONL 存储兼容类，不是当前默认入口
│   │   ├── service.py             # 界面共用的后台任务与本地配置
│   │   ├── cli.py                 # 参数与命令行
│   │   ├── run_realtime.py        # 可直接运行的入口
│   │   ├── download_market_data.py # 原有单次接口诊断工具
│   │   └── data/                  # 旧版采集结果，Git 忽略
│   └── data_dld/                  # Wind 历史数据验证与旧研究脚本
└── tests/                         # 不访问真实网络的自动化测试
```

## 克隆后恢复环境

在已初始化 Conda 的终端中：

```powershell
git clone --branch codex/company-apps https://github.com/vanadium22/Delta1.git
cd Delta1
conda env create --prefix P:\code_content\python_work_env\conda_env\swhy_delta1 --file index_strategy/env/environment.yml
conda activate P:\code_content\python_work_env\conda_env\swhy_delta1
```

环境已存在时只需激活。其他机器可以替换 `--prefix`，环境文件不绑定绝对路径。具体依赖、更新和 Wind 可选依赖见 [环境说明](index_strategy/env/README.md)。

## 桌面应用

在仓库根目录、激活 `swhy_delta1` 后：

```powershell
python -s -m index_strategy.desktop
```

Windows 也可双击 `index_strategy/start_app.cmd`，使用统一目录中的 `swhy_delta1` 环境打开独立窗口。进入「数据下载 → 实时下载」，可查看/修改标的、导入多个 list 文件、选择采集间隔和保存文件夹，开始/停止并查看实时日志。交易数据下载页暂作预留。关窗会等待当前请求完成、数据保存后退出。

桌面采用 CustomTkinter，依赖已写入环境文件；原有环境请先更新依赖。设置保存在 Git 忽略的 `localsetting`。监控区包含整体运行表和可切换标的的行情表，文件保留五档盘口，默认保存在 `Z:\Project_data\realtime_market`。详见 [桌面说明](index_strategy/desktop/README.md)。

实时采集通过 SQLite WAL 事务入库，策略可直接取得只读 DataFrame；Parquet 使用 `data/标的/年/月/日期.内容哈希.parquet`，首批、每分钟及停止时发布增量分片，已发布文件不再改写。读取方法、时间与成交量含义见 [数据与策略接口](index_strategy/instant_dld/README.md)。早期网页入口保留为可选工具，桌面应用不依赖该服务。

## 命令行实时采集

在仓库根目录运行，每 5 秒发起一轮，按 Ctrl+C 结束：

```powershell
python -m index_strategy.instant_dld --interval 5
```

先验证三轮：

```powershell
python -m index_strategy.instant_dld --interval 2 --max-polls 3
```

编辑 `index_strategy/instant_dld/config/symbols.json` 即可维护标的。程序默认直连内网并校验 TLS，需要公司内网/VPN；采集的是接口最新快照，不是交易所逐笔推送。参数、多个标的文件及数据结构见 [实时采集说明](index_strategy/instant_dld/README.md)。

## Wind 历史数据

历史数据入口与实时采集分开，Oracle、pandas、pyarrow 是可选依赖，见 [Wind 说明](index_strategy/data_dld/README_wind_download.md)。

旧脚本中的实际账号已迁到被忽略的 `localsetting/wind_db.json`。克隆后如需 Wind，复制 `config/examples/wind_db.example.json` 到该路径后自行填写，或设置 `WIND_DB_USER`、`WIND_DB_PASSWORD`、`WIND_DB_DSN`。环境变量优先；`WIND_DB_CONFIG` 可指定另一个本地 JSON 配置。仅使用实时接口无需这些 Oracle 配置。

## 测试与 Git

```powershell
python -m unittest discover -s tests -v
```

测试使用临时目录和模拟响应，不连接公司网络。Git 仅保存程序、标的文件、模板、环境定义、文档和测试；`.vscode`、`localsetting`、`.env`、Python 环境、Oracle 客户端、采集数据和运行日志均被忽略。私有标的文件也可放进 `localsetting`，通过 `--symbols-file` 指定。
