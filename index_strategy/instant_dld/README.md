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

频率是相邻轮次的计划开始间隔，支持小数。第一轮立即开始。每轮分批串行请求；若一轮超时或请求耗时超过间隔，跳过已经错过的计划时点，不并发补发。间隔不能保证接口在对应频率更新行情；休市期间可能重复拿到缓存值。默认全天轮询；主力映射使用交易日历，但不据此判断当前是否开盘。

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

## 主力连续标的

可输入 `AU.SHF`，程序实际请求具体合约、仍按 `AU.SHF` 保存。默认读取：

- 逐日主力：`Z:\Project_data\future_investment\data\raw\day\main\month_contract_code.pkl`，日期索引、标的列、具体合约代码值。
- 交易日历：`Z:\Project_data\future_investment\data\normalization\Date.pkl`，`Date` 列或日期索引，需包含下一交易日。该日历由日频数据流程持续更新。

日频文件在当日盘后更新，因此严格使用**当前交易日的前一交易日**那一行，不使用当日行，不向前回填更早主力。例如 2026-09-18 夜盘属于 2026-09-21，使用 2026-09-18 的 `AU.SHF → AU2610.SHF`。商品期货在北京时间 20:00 切换到下一交易日口径，为夜盘提前准备；凌晨和周末按日历延续到下一交易日，中金所代码 `.CFE` 不作夜间提前切换。20:00 是本程序映射切换时间，不代表开盘时间；节假日与周末由本地交易日历确定。夜盘交易日归属参考[上期所交易时间](https://www.shfe.cn/services/calenderandholidays/tradinghours/)。

第一次解析成功后，主力关系按标的和交易日固定并保存到实时库，使用同一保存目录重启也保持不变；下一交易日重新查映射。运行监控显示实际合约、交易日和映射日期。缺少指定日期、空合约、错误文件或日历覆盖不足时，该主力标的明确失败且不请求接口，下一轮重试；同批的其他有效标的继续下载。不会自动猜月份或静默使用过期映射。

主力映射仅用于中国期货，限定 `.SHF/.DCE/.CZC/.INE/.CFE/.GFE` 的纯字母品种代码。原样输入 `AU2610.SHF` 等具体合约、股票或境外市场代码时直接请求，不依赖主力映射文件。桌面「主力映射…」可选择文件、预览并应用路径，随后保存配置或开始采集；命令行可用 `--mapping-file` 和 `--calendar-file`。支持可信本地 pandas Pickle 或同结构 Parquet；Pickle 只应来自自己的数据流程。`normalization/contract_map.pkl` 是交割年月表，不是本功能需要的逐日主力表。

示例保存路径为 `data/AU.SHF/2026/09/2026-09-18.<sha256>.parquet`。`symbol=AU.SHF` 保持连续标识，`source_symbol=AU2610.SHF` 保留实际合约，`mapping_date=2026-09-18`，`trading_date=2026-09-21`。后者是基于采集时刻的映射交易日，接口仍未提供行情本身的交易日期，缓存行情可能滞后。换月原价不复权，策略应检查 `source_symbol` 的变化；换月首条 `volume` 留空，不能对不同合约累计量作差。

旧 SQLite 会在写入器启动时事务升级；v1 行情的实际合约补为原 `symbol`，日期字段留空。已发布 Parquet 不覆盖；成交量 v3 升级会发布修正分片并原子切换目录记录，详见下方口径修正说明。

## 常用参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--interval` / `--frequency` | `5` | 轮询间隔，秒，有限正数 |
| `--symbols-file` | 模块内 `config/symbols.json` | 一个或多个 JSON/TXT/LIST 文件 |
| `--batch-size` | `200` | 单次请求标的上限；不是已确认的服务端限额 |
| `--output-dir` | `Z:/Project_data/realtime_market` | 本机数据目录；相对路径按当前工作目录解析；其他机器可指定自己的目录 |
| `--mapping-file` | 上述 `month_contract_code.pkl` | 逐日主力映射 |
| `--calendar-file` | 上述 `Date.pkl` | 含未来交易日的日历 |
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
│   ├── AU.SHF/2026/09/2026-09-18.<sha256>.parquet
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
| `source_symbol` | 实际请求的合约代码；直接输入具体合约时等于 `symbol` |
| `mapping_date` | 选取主力的上一交易日日期，直接输入具体代码时为空 |
| `trading_date` | 根据采集时刻和日历确定的主力映射交易日，非接口原始交易日期；直接输入具体代码时为空 |
| `quote_time` | 接口 `quoteTimestamp` 的 `HH:MM:SS`；接口未提供交易日期，不拼成假定的交易所 datetime |
| `close` | 最新成交价，来自 `latestPrice` |
| `volume_total` | 接口累计成交数量 `tradedQuantities`，保持来源单位；不使用对应成交额的 `tradeVolume` |
| `volume` | 连续采集的相邻有效快照累计量差；不是固定 1 秒成交量；首次、重启、失败恢复、超长间隔、换日、换约或量/时钟回退时留空 |
| `volume_start` | 本次有效增量的前次采集时间，UTC 秒级 datetime；本行 `timestamp` 为区间结束的采集时间。增量为空时也为空 |
| `volume_interval_seconds` | 两次 HTTP 接收时刻的实际间隔，保留小数秒；不是交易所秒桶时长。增量为空时也为空 |
| `bid_price_1` … `bid_price_5` | 买一至买五价，来自 `b1Price` … `b5Price` |
| `bid_volume_1` … `bid_volume_5` | 买一至买五量，来自 `b1Stocks` … `b5Stocks` |
| `ask_price_1` … `ask_price_5` | 卖一至卖五价，来自 `s1Price` … `s5Price` |
| `ask_volume_1` … `ask_volume_5` | 卖一至卖五量，来自 `s1Stocks` … `s5Stocks` |
| `quality_flags` | 缺失字段、累计量重置等位标记，可组合 |

时间语义是轮询快照。主力按映射交易日建立累计量基准，其他直接代码按采集日期；新运行、该标的上次请求失败或跳过轮次后，首条重新建立基准，不把停机期间所有成交堆到恢复时刻。实际观测间隔大于 `max(2×配置间隔, 配置间隔+1秒)` 时也重建基准。接口缓存未更新时，仍保留本次采样；策略应检查 `quote_time`、采集时间和质量标记，不把成功下载等同于产生了新成交。价格与数量保持接口原始单位，不自动换算手、股或合约乘数。

2026-09-18 实测 `AU2610.SHF` 只提供一档有效盘口；二至五档价格为 `9223372036854.775`（INT64_MAX / 1e6）占位值。该值和零盘口价格转为 null，盘口量保留来源值，不伪造缺失档位。有效最新价缺失、非正或为占位值时，该标的作为失败记录，不插入新的行情行。

`quality_flags`：`1` 累计量缺失；`2` 盘口字段缺失；`4` 接口时间缺失/无效；`8` 累计量基准无效、量/接口时钟/采集时钟回退；`16` 首条、新运行、中断恢复或换日后无连续基准；`32` 发现接口价格占位值；`64` 实际合约发生切换；`128` 观测间隔超过允许阈值。价格及不可计算增量在 pandas 中呈现为 NaN。

## 与历史 1 秒成交量的区别及修复

核对基准：`Z:/Project_data/intraday_timestamp/normalization/v1/cn_futures_main_1s`，版本 `20260918T103821501589Z-473b3e4c`。该库把同一源时间秒内 iFind 快照增量 `vol` 求和为 `volume`，时间标签是秒桶结束（源秒 + 1 秒）。缺秒或竞价情况下，其 `bar_start` 可以为空。实时接口只有累计量与 `HHMMSS`，无法从 2 秒轮询还原中间每秒成交分布；即使设为 1 秒，缓存延迟和不完整快照也不能保证与历史秒桶逐条相等。不能把区间量除以间隔当成真实单秒成交量。

实测实时累计 `80047 → 80053` 对应观测区间约 2 秒的增量 `6`，应与历史多个秒桶的合计在时间和合约一致后比较。9/18 夜盘属于 9/21 交易日，不能直接与历史 9/18 交易日文件对比。历史 9/18 AU.SHF 秒量合计 `248571`，日频量 `248802`，两者处于同一数量级；没有依据按黄金合约乘数 1000 换算成交量。历史文件与实时源的单位元数据均尚未认证，当前也没有重叠实时样本用来证明两个供应商单位完全相同。历史秒库不含盘口量，无法用它校准买卖挂单量。

v3 修复曾跨运行计算的增量（例如停机 581 秒后恢复的 `2991`），并补齐可确认的观测区间。升级前使用 SQLite backup API 创建 `live/backups/quotes.pre-volume-v3.<运行编号>.sqlite3`；在单个事务中重算旧行、发布新的不可变 Parquet、替换 `parquet_parts` 目录记录。历史文件保留，其旧目录记录转入 `retired_parquet_parts`，读取请使用 `RealtimeReader`，不要把目录下所有文件 glob 后合并，以免重复。

升级期间读者仍可读旧快照，提交后读取修正版本。发布或数据库操作失败会回滚原目录和旧库，保留的未登记新文件不会被读取。尚未升级的 v1/v2 数据若通过新版 reader 打开，其增量暂时留空，累计量正常保留；启动写入器后根据原库运行/批次记录修复。原有文件可作审计，不覆盖历史秒库。

## 策略实时读取与结果保存

在仓库根目录、激活项目环境后：

```python
from index_strategy.instant_dld.reader import RealtimeReader, write_strategy_frame

reader = RealtimeReader()  # 默认 Z:\Project_data\realtime_market
df = reader.latest(["AU.SHF"])  # 每个标的最近一条有效行情
print(df[["symbol", "source_symbol", "close", "volume", "volume_interval_seconds", "volume_total"]])

cursor = 0  # 持续策略需自行保存已处理的 sequence
new_rows = reader.read_since(cursor, symbols=["AU.SHF"])
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
