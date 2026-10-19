# 国内 A 股指数与股指期货数据格式规范 v1

日期：2026-09-30。范围以用户本次更正为准：**国内 A 股指数，以及 IF、IH、IC、IM 的具体年月合约**。所有历史数据未来重新下载。本方案不注册、不导入已有商品期货、港股、美股或其他历史库。测试样例均为合成数据。

本规范用于未来下载程序与独立桌面看板之间的交接。看板不绑定供应商，也不要求下载程序依赖看板前端。参考实现：`dashboard/marketdata/bars.py`；实时观测适配器：`dashboard/marketdata/adapters.py`。

2026-10-01 实施更新：原生 App 已实现数据源选择、按日/分/秒窗口读取、多频公式 v2、图表与历史回放；启动和操作见 [../native/README.md](../native/README.md)。真实数据源默认仍为空。下述数据格式继续使用 v1，未导入任何已有其他市场历史库。

## 1. 数据分四层

| 层 | 内容 | 读取方式 |
| --- | --- | --- |
| 原始证据 raw | 供应商原始响应、请求范围、下载时间、来源、字段解释 | 下载模块保存，日常看板不直接扫描 |
| 标准历史 bars | 日频、1 分钟、真实 1 秒 bar，分别声明频率 | Parquet + 注册 manifest，只读 |
| 实时 observations | 每次轮询的报价、盘口、累计量、实际接收时间 | 当前采集模块 SQLite 游标；归档 Parquet |
| 参考数据 reference | 标的、挂牌合约、到期日、交易日历、会话、别名映射 | 独立版本文件，按日期及当时可知时间读取 |

**1 秒轮询观测不是 1 秒成交 bar。** 下载不到真正秒级 bar 时，保存 `quote_observation` / `quote_snapshot`，不能改频率标签冒充 `1s` bar。

## 2. 目录可以自选

用户选择总根目录，例如 `<自选目录>/cn_index_market/`。程序不能写死 P、Z、T 盘。总根目录下每个标准数据集使用独立根目录：

```text
<自选总根目录>/
  raw/<source_id>/...                         原始数据和下载日志
  datasets/<dataset_id>/
    dataset.json                             数据集身份和口径
    current.json                             最后成功发布的版本指针
    versions/<version>.json                   不可变文件清单、覆盖范围、检查点
    data/1d/<instrument_id>/YYYY/MM/<交易日>.<sha256>.parquet
    data/1m/<instrument_id>/YYYY/MM/<交易日>.<sha256>.parquet
    data/1s/<instrument_id>/YYYY/MM/<交易日>.<sha256>.parquet
    writer.lock                              单写者锁
  reference/<dataset_id>/...                  日历、挂牌合约、映射等
```

同一数据集允许包含多种频率，但供应商、价格口径、单位与可用时间政策必须兼容。口径不同应创建另一 `dataset_id`，例如指数和期货的成交量不能未经声明混存成同一个单位。

实时热库和因子结果库分别选目录，不要求与历史库同盘。当前采集器的 SQLite WAL **要求本机磁盘**，网络映射盘会被现有代码拒绝。历史 Parquet 可以单独放大容量磁盘；网络文件系统的写锁与原子替换可靠性需要实测，未验证时用本地发布、再同步只读副本。

原生 App 初次启动无已绑定数据源，选择目录并验证后才启用。`sources.example.json` 保留为概念配置模板；实际原生配置为 `dashboard/localsetting/native.json`，由 App 写入，独立于旧预览配置。

## 3. 文件格式

标准层使用长表 Parquet，Zstandard 压缩；每行一个标的、一个区间、一个修订版本。CSV 可以作为原始交换文件，经显式类型校验后发布 Parquet；不把 pickle 宽表作为未来交接格式。

时间使用 Arrow `timestamp[ns, tz=UTC]`；显示时转换为 `Asia/Shanghai`。保持源精度，**ns 容器不代表来源具有纳秒精度**。`trade_date` 使用 `date32`。浮点值使用 float64，未知为 null，禁止用 0、NaN、Infinity 或哨兵价代替未知。

采用 Parquet 是为了按字段、标的分片和时间范围读取，避免每次计算加载全部秒级历史；依据 [Arrow Parquet 文档](https://arrow.apache.org/docs/python/parquet.html)与[Dataset 文档](https://arrow.apache.org/docs/python/dataset.html)。参考实现已在本机 pyarrow 24 上测试。

## 4. bar 字段

机器可读字段表见 `examples/bar_fields.json`，实际 Arrow schema 为 `dashboard.marketdata.BAR_SCHEMA`。字段必须与 schema 一致，新增业务字段应升级 schema，不能静默改含义。

| 字段 | 类型 | 要求与含义 |
| --- | --- | --- |
| instrument_id | string | 必填。指数规范代码；期货必须为具体合约，如 IC2610.CFE |
| frequency | string | 必填，只接受 1d / 1m / 1s |
| event_time | UTC timestamp ns | 必填，bar 结束时间，不是下载时间 |
| bar_start | UTC timestamp ns / null | 已知则填写真实区间开始；未知留 null，不推造 |
| trade_date | date32 | 必填，由已核验的交易所日历确定，不用服务器日期替代 |
| session_id | string / null | 如 day_am、day_pm、opening_auction、closing_auction；必须有会话定义 |
| source_symbol | string / null | 供应商原始代码，保留映射证据 |
| open / high / low / close | float64 / null | 真实 OHLC；只下载到末价时其余留 null |
| volume | float64 / null | **该 bar 区间内增量成交量**，禁止日累计量混入 |
| turnover | float64 / null | 区间成交金额；币种、缩放、统计口径必须声明 |
| open_interest | float64 / null | 期货区间末持仓量；指数留 null |
| settlement | float64 / null | 结算价，通常日频使用，与 close 不等同 |
| prev_close | float64 / null | 供应商核验的前收盘；不能用采集开始时首笔价替代 |
| is_final | bool | 必填，已结束且正式发布为 true；待修订为 false |
| revision | int64 | 必填，非负。同一逻辑键的真实修订递增 |
| available_at | UTC timestamp ns / null | 必填字段，可为 null。该内容或该修订最早可被使用的时间 |
| recorded_at | UTC timestamp ns | 必填，本次原始数据被下载并写入标准层的真实时间 |
| quality_flags | uint32 | 必填，规范层质量标记；0 不保证没有其他来源限制 |
| source_quality_flags | uint32 / null | 供应商或原始转换器质量标记，定义另存，不能覆盖规范标记 |
| sample_count | uint32 / null | 构造 bar 的真实源观测数量；不知道则 null |

必填字段集合：`instrument_id, frequency, event_time, trade_date, is_final, revision, available_at, recorded_at, quality_flags`。其他字段也存在于标准 Parquet schema 中，但可为空。缺失列在入库校验后补为 null，不补价格或成交量。

核心价格指标要求 close；真实 OHLC 图要求完整 OHLC；成交量或 VWAP 指标要求相应字段与已核验单位。不能因为 schema 容许 null 就显示一个无法计算的指标为 0。

## 5. 时间、区间与可用时间

1. 普通连续竞价 bar 采用区间开始包含、结束不包含的 `[bar_start, event_time)`，标签为结束时间。供应商使用其他边界时要记录其定义并转换；集合竞价和收盘整点需单独说明，不能重复归入两个 bar。
2. 1m 已知区间长度为 60 秒，1s 为 1 秒；日频长度由会话定义，不强行设为 24 小时。午休、非交易日与集合竞价不能按连续自然秒补齐。
3. 股票指数与股指期货的会话分别下载并核验，不借用商品期货夜盘规则。
4. `event_time` 是结束标签；`available_at` 是可以计算使用的时间；`recorded_at` 是本程序实际拿到数据的时间。三者不可混用。
5. 日频数据不能把午夜时间作为当天收盘已知时间。日频 close、settlement 的发布时点可能不同；无法获得逐字段可用时间时，本行统一使用所有被用字段中最晚的可用时间，或者拆成独立数据集。
6. 历史源无法提供真实 `available_at` 时，可留 null；或显式声明 `assumed_bar_end_plus_delay` 与延迟，并设置质量位。假设时间不能标成实测值。
7. 回看“修订后的历史”与“当时实际已经入库的历史”是两种查询。前者用 `as_of` 筛行情可用时间；后者还用 `knowledge_at` 筛 `recorded_at`。今天补下来的历史不能作为过去程序已经知道它的证据。

参考实现默认排除未知 `available_at`，可通过 `allow_unverified_availability=True` 显式放行用于标注过的研究/展示；默认排除未完成 bar。真实可用时间未知时，不宣称回放已经证明没有未来信息。

## 6. 标的、价格、成交量

`dataset.json` 必须包含 `instruments` 注册表。每个标的至少声明 `asset_type=cn_index|cn_index_future`、`market_region=CN`。建议另外声明名称、交易所、人民币币种、价格单位、volume/turnover 单位、交易日历 ID、源时间精度、数据发布节奏和能力列表。

期货 bar 只保存 `IF/IH/IC/IM` + 四位年月 + `.CFE` 的实际合约。月份合法性、挂牌状态及到期日还需来自新下载的合约参考表；仅通过代码正则不能证明该合约已经挂牌。

指数价格单位为指数点；股指期货报价为指数点。成交量的“手 / 单边 / 双边”、金额单位及供应商缩放要核验。指数的 volume 可能是成份股汇总源口径，不能直接标为期货手数，更不能与期货量相加。单位未知时使用 `source_native_unverified`，相关指标显示受限。

价格调整使用 `price_adjustment` 描述。具体期货保持未复权真实价格，不把连续合约复权价当作实际月份成交价。来源、复权、单位变化创建新的数据集，不在原数据集悄悄更换。

## 7. 别名与连续序列

`IC00.CFE`、`IC01.CFE` 是看板约定的到期顺序别名，不是永久合约身份。标准历史表不重复存 alias bar；另存映射：

```text
alias, trade_date, concrete_instrument_id,
valid_from, valid_to, known_at, mapping_source, mapping_version
```

映射按该历史日期解析；不能把今天 IC00 对应的实际合约套到过去。换月时依据计算目标，重置指标窗口，或使用另行定义并标注的拼接研究序列。具体合约价差必须在同一历史时刻取两个实际合约。

主力映射如果由成交量/持仓量选出，必须说明选择规则及何时知道，避免用当天收盘统计提前定义当天盘中主力。没有可靠证据时不自动生成主力。

当前实时采集器可保存 alias 与 concrete 两份行；它们只是一笔观测的两个身份，适配器按稳定 observation_id 去重。标准历史表不能把两份成交量加起来。

## 8. 增量发布协议

逻辑主键：日频为 `(dataset_id, instrument_id, 1d, trade_date)`；分钟和秒级为 `(dataset_id, instrument_id, frequency, event_time)`。存储修订主键再加 `revision`。

1. 下载程序读取该数据源自己的检查点，并对近期区间做重叠重抓。检查点按来源、标的、频率维护，不能仅记录全库最大日期。
2. 相同逻辑键、相同 revision、相同业务内容：幂等跳过。仅下载时间改变不构成新 revision。
3. 相同键和 revision，内容不同：报告冲突，不静默覆盖，核验后递增 revision。
4. 更早日期补洞与迟到数据可以追加；增量不是只能往时间末尾写。
5. 先将新 Parquet 写同目录临时文件、flush/fsync、原子发布；再发布不可变版本 manifest；最后原子替换 `current.json`。
6. 检查点写进成功发布的 manifest。中途失败不能推进已发布检查点。重启重放同批应幂等。
7. manifest 登记文件相对路径、SHA256、行数、标的、频率、交易日和事件时间范围。读者只读登记分片，**不能 glob 所有 Parquet**，否则孤儿文件与旧压缩文件会重复计算。
8. 每次指标计算冻结版本；记录来源版本和对应检查点。旧版本可回看，不覆盖原文件。
9. 后续压缩小文件应生成新快照、更新活动分片集合；未制定保留规则前不能删除被旧版本引用的文件。参考实现目前不自动压缩或清理。

源没有 revision 时，由下载器维护该逻辑键的本地修订序号：初次为 0，核验后的内容变化为当前最大 revision+1；不能每次重抓都生成新 revision。新挂牌合约可用 `register_instruments()` 追加注册，不能修改已注册标的的单位/含义；旧 manifest 保留当时的数据集说明。标的注册不代替实际挂牌参考资料。

参考实现使用单写者文件锁。重复内容全部被跳过时不会单独更新检查点；实际下载器应记录空响应审计，并在业务确认后补充专门的空提交协议。本模块没有实现供应商下载任务或缺口扫描。

## 9. 成交量与重采样限制

- volume 必须为已确认区间增量。累计量先按照源交易日、会话和重置规则作差；首笔、断线、重启或重置无法确定增量时为 null。
- 缺少 bar 不是成交量 0。只能在供应商确认该完整区间没有成交时写 0。
- 连续无重叠完整 1s bar 可以聚合成 1m；OHLC 依次为首开、最高、最低、末收，volume/turnover 求和，持仓量取区间末值。
- 只有 close 的秒序列不能得到真实成交 OHLC；得到的是抽样价格极值，必须声明为 sampled_price 派生产品。
- 秒级有缺口、单位变化或区间未知时，不能把不完整分钟显示成完整行情。
- 1m 可以构造会话聚合日数据，但不能冒充供应商正式日收盘/结算价。1d 不能拆成 1m，1m 不能插值伪造 1s。
- 当前实时 `volume` 可能覆盖 2.5 秒等接收间隔，不能均分后声称是真实秒量，也不能与历史 bar 重叠叠加。

## 10. 质量位 v1

| 位值 | 名称 | 含义 |
| --- | --- | --- |
| 1 | availability_assumed | 可用时间采用假设 |
| 2 | trade_date_inferred | 交易日待核验 |
| 4 | units_unverified | 单位或缩放未认证 |
| 8 | interval_unknown | bar_start 或区间边界未知 |
| 16 | source_time_unverified | 源日期/完整时刻未确认 |
| 32 | sampled_not_full_bar | 抽样而非完整成交 bar |
| 64 | ohlc_unavailable | 只有 close 或不完整 OHLC |
| 128 | coverage_gap | 覆盖缺口或区间不完整 |

源标记独立存 `source_quality_flags`。本参考校验器检查类型和基本时间/数值约束，不代替供应商完整性、交易日历、单位、挂牌合约认证；这些必须由下载流程另行验证并记录。

## 11. 本轮实际实现与边界

已实现：typed schema、基础校验、自选 root、单写者、不可变分片/manifest、重叠导入幂等、修订冲突阻止发布、冻结旧版本、按标的/频率/时间筛选和字段投影、available_at 与 recorded_at 查询条件。

实时桥接只在调用者指定新库目录和标的白名单后读取，不注册任何历史库；保留全精度 received_at、盘口与接收区间成交量，返回源库游标，alias/concrete 共用 observation_id。跨分页调用者也应按该 ID 去重。

2026-10-01 增加：显式 repository、多频窗口、受限指标 v2、秒级真实 bar 读取、原生数据源/路径 UI、按可用时间回放、结果重启读取和不变输入去重。参考 `reference.json` 的可执行结构见 [reference.example.json](reference.example.json)与原生操作文档。

尚未实现：真实历史下载器、参考日历/映射下载器、交易会话认证、秒级自动重采样、全历史因子断点补算和大规模性能验收。当前网页初版不会自动调用本模块。不迁移或改变现有生产数据。
