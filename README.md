# Delta1

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
git clone https://github.com/vanadium22/Delta1.git
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
