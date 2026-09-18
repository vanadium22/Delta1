# 实时行情轮询与保存

`run_realtime.py` 和 `python -m index_strategy.instant_dld` 是同一入口。默认直连内网、验证 TLS，每 5 秒请求一轮，直到 Ctrl+C。请求只获取行情，不提交交易。默认保存位置为 `Z:\Project_data\realtime_market`，行情采用 Parquet，策略通过实时事务库取得只读 DataFrame。

## 运行

在仓库根目录、激活 `swhy_delta1` 后：

```powershell
python -m index_strategy.instant_dld --interval 5
python -m index_strategy.instant_dld --interval 0.5 --max-polls 3
python -m index_strategy.instant_dld --once
python index_strategy/instant_dld/run_realtime.py --interval 10
```

频率是相邻轮次的计划开始间隔，支持小数。第一轮立即开始。每轮分批串行请求；若一轮超时或请求耗时超过间隔，跳过已经错过的计划时点，不并发补发。间隔不能保证接口在对应频率更新行情；休市期间可能重复拿到缓存值。程序不内置交易日历，默认全天轮询。

## 维护标的

默认文件为 `config/symbols.json`，内容是普通字符串 list：

```json
["603110.SH", "000001.SZ"]
```

支持多个文件，合并并保留首次出现的顺序、去重，代码统一大写：

```powershell
python -m index_strategy.instant_dld --interval 5 --symbols-file index_strategy/instant_dld/config/symbols.json localsetting/extra_symbols.txt
```

`.json` 使用 JSON list；`.txt`、`.list` 可每行一个代码（空行和 `#` 注释忽略），也可保存 Python 字面量 list，例如 `['603110.SH', '000001.SZ']`。不会执行 `.py` 文件。代码必须是字符串，以免丢失 `000001` 的前导零。

每轮开始重新读取文件，保存后下一轮生效。启动时文件无效、丢失或合并列表为空会直接报错；运行中出现这种情况会记录 `symbol_reload_error`，沿用上一版有效标的，修复文件后自动恢复。空列表不会暂停程序，需要暂停时按 Ctrl+C。

## 常用参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--interval` / `--frequency` | `5` | 轮询间隔，秒，有限正数 |
| `--symbols-file` | 模块内 `config/symbols.json` | 一个或多个 JSON/TXT/LIST 文件 |
| `--batch-size` | `200` | 单次请求标的上限；不是已确认的服务端限额 |
| `--output-dir` | `Z:/Project_data/realtime_market` | 本机数据目录；相对路径按当前工作目录解析；其他机器可指定自己的目录 |
| `--max-polls` | `0` | 0 为持续运行，正整数表示有限轮数 |
| `--once` | 关闭 | 只采集一轮，与 `--max-polls` 互斥 |
| `--direct` | 开启 | 不使用环境代理、环境 CA、netrc |
| `--use-env-proxy` | 关闭 | 使用 Requests 的环境设置 |
| `--connect-timeout` | `10` | 建连超时，秒 |
| `--read-timeout` | `30` | 接收数据的读取等待超时，秒；并非整轮总时限 |
| `--ca-bundle` | 公共可信 CA | 指定公司可信 CA 文件，始终验证 TLS |
| `--url` | 当前已验证接口 | 也可由 `SWHY_MARKET_DATA_URL` 提供 |

本机验证中，环境代理模式超时，直连成功。网络或业务失败会记录后继续下一轮，不在同一轮立即重试。Ctrl+C/SIGTERM 会等待当前请求完成或超时，保存摘要后退出。磁盘写入失败会停止采集，防止出现持续请求却没有落盘的情况。

## 保存目录与发布

```text
Z:\Project_data\realtime_market\
├── data/
│   ├── AU2610.SHF/2026/09/2026-09-18.<sha256>.parquet
│   └── 000001.SZ/2026/09/2026-09-18.<sha256>.parquet
├── live/
│   ├── quotes.sqlite3           # 行情、批次结果、运行摘要、事件和 Parquet 文件目录
│   ├── quotes.sqlite3-wal       # SQLite 管理，程序运行中不要手动移动/删除
│   └── quotes.sqlite3-shm
├── strategy_results/<策略名>/  # 策略计算结果，独立 Parquet 文件
└── .writer.lock                # 操作系统持有的写入锁，进程退出自动释放
```

采用参考数据集的 `标的/年/月/日期.哈希.parquet` 结构。这里每个文件是互不重叠的增量分片，一天可有多个文件；目录日期是北京时间的**采集日期**。原始 JSON 响应不再作为默认行情文件保存，运行记录也存入 SQLite。

每个请求批次先用 SQLite WAL + FULL 同步事务提交全部有效行情与批次结果。首批立即发布 Parquet，后续每 60 秒在批次结束后检查归档，正常停止/关窗会补齐全部未归档记录。轮询间隔超过 60 秒时，发布也要等下一批结束。策略读取实时库，无需等待归档。

Parquet 先写同目录临时文件，关闭并 fsync 后重命名发布，最后登记到数据库文件目录。已发布文件不再修改或自动删除。若进程在发布后、登记前中断，可能留下未登记文件；策略使用 `parquet_files` / `read_parquet_day` 读取已登记文件，避免直接 glob 把这种孤立文件重复算入。重启后首次归档或正常关闭会补齐已提交但未归档的记录。

本机 Z 盘已验证是本地磁盘。WAL 的多个进程必须位于同一台电脑；程序拒绝 Windows 网络共享盘作为实时库位置。此设计依据 [SQLite WAL 并发与限制](https://www.sqlite.org/wal.html)。不要在程序运行时单独复制数据库主文件作为备份，WAL 中可能还有已提交数据。

## 字段与时间含义

| 字段 | 含义 |
| --- | --- |
| `sequence` | 跨运行递增的记录编号，策略增量游标；同秒多条记录也不会冲突 |
| `timestamp` | HTTP 响应接收时刻，向下取整到秒，保存为带 UTC 时区的 datetime；界面显示北京时间 |
| `symbol` | 标的代码，保留前导零 |
| `quote_time` | 接口 `quoteTimestamp` 的 `HH:MM:SS`；接口未提供交易日期，不拼成假定的交易所 datetime |
| `close` | 最新成交价，来自 `latestPrice` |
| `volume_total` | 接口累计成交数量 `tradedQuantities`，保持来源单位；不使用对应成交额的 `tradeVolume` |
| `volume` | 相邻有效采样的累计量差；首次、跨采集日期、累计量回退或接口时钟回退时留空 |
| `bid_price_1` … `bid_price_5` | 买一至买五价，来自 `b1Price` … `b5Price` |
| `bid_volume_1` … `bid_volume_5` | 买一至买五量，来自 `b1Stocks` … `b5Stocks` |
| `ask_price_1` … `ask_price_5` | 卖一至卖五价，来自 `s1Price` … `s5Price` |
| `ask_volume_1` … `ask_volume_5` | 卖一至卖五量，来自 `s1Stocks` … `s5Stocks` |
| `quality_flags` | 缺失字段、累计量重置等位标记，可组合 |

时间语义是轮询快照，`volume` 是两次有效采样之间的增量，遇到漏采或暂停可能跨多个轮询间隔。接口缓存未更新时，仍保留本次采样；策略应检查 `quote_time`、采集时间和质量标记，不把成功下载等同于产生了新成交。价格与数量保持接口原始单位，不自动换算手、股或合约乘数。

2026-09-18 实测 `AU2610.SHF` 只提供一档有效盘口；二至五档价格为 `9223372036854.775`（INT64_MAX / 1e6）占位值。该值和零盘口价格转为 null，盘口量保留来源值，不伪造缺失档位。有效最新价缺失、非正或为占位值时，该标的作为失败记录，不插入新的行情行。

`quality_flags`：`1` 累计量缺失；`2` 盘口字段缺失；`4` 接口时间缺失/无效；`8` 累计量或接口时钟回退；`16` 没有同采集日的前次采样；`32` 发现接口价格占位值。价格缺失在 pandas 中呈现为 NaN。

## 策略实时读取与结果保存

在仓库根目录、激活项目环境后：

```python
from index_strategy.instant_dld.reader import RealtimeReader, write_strategy_frame

reader = RealtimeReader()  # 默认 Z:\Project_data\realtime_market
df = reader.latest(["AU2610.SHF"])  # 每个标的最近一条有效行情
print(df[["symbol", "close", "volume_total", "bid_price_1", "ask_price_1"]])

cursor = 0  # 持续策略需自行保存已处理的 sequence
new_rows = reader.read_since(cursor, symbols=["AU2610.SHF"])
if not new_rows.empty:
    result = new_rows[["sequence", "symbol", "close"]].copy()
    # 在这里执行你的策略计算。
    output = write_strategy_frame(result, "my_strategy")
    cursor = int(new_rows["sequence"].max())  # 处理成功后再推进游标
```

所有查询使用 `mode=ro` 和 `query_only`，每次查询完成就关闭连接，然后才把 DataFrame 交给策略计算。读取长计算不会持续占用数据库事务。行情由单个采集进程写入，策略结果写到 `strategy_results/<策略名>` 的独立新文件，不覆盖行情和其他策略结果。第二个采集进程写同一根目录会被锁拒绝；读者不需要该锁。

`read_since` 默认每次最多 10,000 行，历史较多时循环取下一批；不要用秒级时间戳代替游标，因为小数频率可能在同秒产生多条采样。`latest` 在下载失败期间仍能返回最近一次有效值，应自行检查时间。数据库当前保留全部历史，不自动清理。

历史 DataFrame 和 Parquet 文件：

```python
history = reader.history("AU2610.SHF", "2026-09-18")  # 包含尚未归档的新记录
archived = reader.read_parquet_day("AU2610.SHF", "2026-09-18")
files = reader.parquet_files("AU2610.SHF", "2026-09-18")

import pandas as pd
single_file = pd.read_parquet(files[0])  # 普通 Parquet，可独立阅读
```

也可运行 `python -m index_strategy.instant_dld.read_example --symbol AU2610.SHF` 查看最近行情；加 `--save-result` 可演示保存独立计算结果。

失败的 HTTP/业务请求不会产生替补行情行，失败标的和原因保留在 `batches` 表及运行监控中。归档失败会停止任务；已经提交的实时数据保留，可在问题修复后补归档。退出码：`0` 正常且批次全部成功，`2` 包含部分/失败批次，`1` 配置或本地运行错误。旧 `download_market_data.py --direct` 仍可作单次诊断，`storage.py` 仅保留旧 JSONL 类供兼容用途。
