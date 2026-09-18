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
│   ├── frontend/                  # 本地网页界面、运行控制与实时日志
│   ├── instant_dld/
│   │   ├── config/symbols.json     # 维护标的列表，可增加多个 JSON/TXT/LIST 文件
│   │   ├── client.py              # HTTP 请求和业务响应检查
│   │   ├── symbols.py             # 标的读取、合并、校验
│   │   ├── collector.py           # 轮询、重新加载标的、分批及停止
│   │   ├── storage.py             # 按天保存 JSONL 和运行摘要
│   │   ├── cli.py                 # 参数与命令行
│   │   ├── run_realtime.py        # 可直接运行的入口
│   │   ├── download_market_data.py # 原有单次接口诊断工具
│   │   └── data/                  # 本机采集结果，Git 忽略
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

## 网页界面

在仓库根目录、激活 `swhy_delta1` 后：

```powershell
python -m index_strategy.frontend --open
```

打开 `http://127.0.0.1:8766`，进入「数据下载 → 实时下载」，可查看/修改标的、采集间隔和保存目录，开始/停止任务并查看实时日志。交易数据下载页暂作预留。页面设置保存在 Git 忽略的 `localsetting`；不增加环境依赖。详见 [界面说明](index_strategy/frontend/README.md)。

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
