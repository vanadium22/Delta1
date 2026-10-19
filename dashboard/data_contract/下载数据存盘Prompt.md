# 可复制的未来下载任务 Prompt

将下面正文复制给将来编写下载程序的助手，把【】替换为实际要求。这里要求未来重新下载的数据，不接入任何已有其他市场数据。

---

请为我的国内 A 股指数和股指期货看板开发数据下载与增量存储程序。

## 任务范围与输入

- 仅国内 A 股指数，以及 IF、IH、IC、IM 的具体年月合约；不包括商品期货、港美股、股票个股、ETF、期权或国债期货。
- 指数列表：【例如 000300.SH、000016.SH、000905.SH、000852.SH，以及我额外指定的 A 股指数】。
- 股指品种：【例如 IF、IH、IC、IM】。下载指定历史区间内实际挂牌的全部所需具体合约，不能只抓当前主力或把今天的合约表套到过去。
- 来源与授权方式：【供应商/API及我已提供的访问方式】。不得在文件中保存访问密钥或认证头。
- 频率与时间范围：【1d/1m/真实1s，起止交易日】。来源不提供某频率时明确报告，不通过插值或反推伪造。
- 数据总根目录：【我自选的完整路径】。程序参数化 root，不硬编码盘符。
- 统一采用本项目 `dashboard/data_contract/README.md` 的 `dashboard_bars_v1`。有代码访问条件时复用 `dashboard.marketdata.BarDataset` 和 `BAR_SCHEMA`；否则按相同规范实现。
- 这是新的数据下载任务，不导入、拼接或绑定现有商品/其他市场历史库。

## 先确认源字段含义

先输出来源能力和字段说明，核验：代码映射、交易日历、开始/结束标签、时区、时间精度、发布节奏、OHLC 是否真实、volume 是区间增量还是日累计、成交量单双边/手数、金额缩放/币种、持仓量、正式结算价、可用时间、价格复权。

只确认供应商实际保证的内容；未知内容记录为 unknown/unverified，不能猜成已确认。如果只能拿到 1 秒轮询快照，将其存为 quote_observation，不称为真实 1s bar。只有最新价时不生成虚假的 open/high/low。

## 标准 bar 格式

长表 Parquet + Zstandard。每行一个标的、一个区间、一个 revision。完整 Arrow schema 的列为：

```text
instrument_id: string
frequency: string                     # 1d / 1m / 1s
event_time: timestamp[ns, UTC]          # bar 结束时间
bar_start: timestamp[ns, UTC] nullable
trade_date: date32
session_id: string nullable
source_symbol: string nullable
open, high, low, close: float64 nullable
volume, turnover, open_interest: float64 nullable
settlement, prev_close: float64 nullable
is_final: bool
revision: int64
available_at: timestamp[ns, UTC] nullable
recorded_at: timestamp[ns, UTC]
quality_flags: uint32
source_quality_flags: uint32 nullable
sample_count: uint32 nullable
```

必填字段集合：instrument_id、frequency、event_time、trade_date、is_final、revision、available_at、recorded_at、quality_flags。available_at 字段必须存在，内容无法确认可以为 null。其他列不能擅自填价格或量，不知道就留 null。禁止 NaN、Infinity、0 或哨兵价表示缺失。

保留源精度，不因为使用 ns 类型就宣称纳秒行情。所有输入时间必须有明确时区；无时区的源字段须依据供应商文档显式本地化，再转 UTC。展示为 Asia/Shanghai。

普通连续竞价 bar 使用 [bar_start,event_time)；如供应商边界规则不同，记录并转换，集合竞价和收盘整点单独处理。1m 区间 60 秒，1s 区间 1 秒。午休、休市与缺口不生成填充行情。

日频按交易日存储，event_time/available_at 必须体现真正会话结束/发布规则，不能把当天午夜当作当天收盘可用时刻。available_at 采用假设时，在 dataset.json 声明 `assumed_bar_end_plus_delay` 和延迟并设置 quality_flags 的 1 位；未知留 null。recorded_at 是此次真实下载入库时间，不能伪造成历史时间。

volume 只放已确认的区间增量；累计源量要按源交易日与重置规则转换。无法确定首笔或断线间隔增量时留 null。指数和期货成交量单位分别声明，不作未经确认的转换。settlement 与 close 分列。

期货标准表只使用具体合约代码，如 IC2610.CFE；原始代码放 source_symbol。IC00/01 和主力标签另存映射，不重复写成可求和的历史 bar。

## 目录与数据集元信息

```text
<root>/raw/<source_id>/...
<root>/datasets/<dataset_id>/dataset.json
<root>/datasets/<dataset_id>/current.json
<root>/datasets/<dataset_id>/versions/<version>.json
<root>/datasets/<dataset_id>/data/<frequency>/<instrument_id>/YYYY/MM/<trade_date>.<sha256>.parquet
<root>/reference/<reference_dataset_id>/...
```

dataset.json 至少包含 dataset_id、source_id、series_kind、price_adjustment、volume_unit、availability_policy、instruments，及 schema_version=dashboard_bars_v1、timezone=UTC、timestamp_semantics=bar_end。instruments 中每个标的含 asset_type=cn_index|cn_index_future、market_region=CN；另外注明价格/金额单位、能力、源时区/精度、时间政策和质量限制。单位或复权口径变化另建数据集。

请同时下载并保存：实际挂牌合约的 listing_date/expiry_date/underlying/multiplier 等参考资料；A 股指数与股指期货各自的交易日历/会话；历史别名映射。每份参考资料包含来源、版本与 known_at，不能将未来信息倒灌。

App 当前参考资料入口是独立 `reference.json`，结构为 `{"schema_version":"cn_index_reference_v1","contracts":[...],"aliases":[...]}`。contracts 每行至少 instrument_id、listing_date、expiry_date、known_at，日期用 YYYY-MM-DD；known_at 带时区。aliases 每行至少以下映射列，valid_from/valid_to/known_at 带时区，生效区间左闭右开；当前本地 00–03 只映射到相同 IF/IH/IC/IM 品种的具体合约。`reference.example.json` 是空结构模板，不含真实挂牌结论。

别名映射列：alias、trade_date、concrete_instrument_id、valid_from、valid_to、known_at、mapping_source、mapping_version。主力如果没有可核验规则与当时可知时间，暂时不生成。

## 增量、修订和恢复

日频逻辑键为 dataset_id+instrument_id+1d+trade_date；分钟/秒级为 dataset_id+instrument_id+frequency+event_time；修订存储键再加 revision。

- 相同键、revision 和业务内容重复下载时幂等跳过；单纯 recorded_at 改变不算修订。
- 相同键和 revision 内容不同时报冲突，不能静默覆盖。核验后的真实修订递增 revision，并保留旧版。
- 源无 revision 时，本地按逻辑键维护：首次 0，核验后的业务内容变化才递增；重复重抓不递增。新挂牌合约追加注册，已注册标的口径不能原地修改。
- 为近期区间重叠重抓，支持更早日期补洞、迟到数据和历史修订；不要只按全库最大日期断点续传。
- 检查点按来源、标的、频率保存，并与成功发布的 manifest 一起提交。失败不推进检查点。
- 单写者。先写临时分片并 flush/fsync，再原子发布不可变 Parquet；发布含相对路径、SHA256、行数和覆盖范围的不可变 manifest；最后原子替换 current.json。
- 读取只能使用已注册活动分片，不能 glob 全部 parquet。崩溃留下的临时/孤儿文件不应被读者使用。
- 若复用当前参考实现，完全重复的空增量不会更新检查点；空响应与“确实无数据”的检查点需另做有审计证据的发布协议。
- 记录每次抓取请求范围、实际返回范围、缺口、错误和行数。原始响应只留行情与安全请求元信息，不保存密钥。
- 保留现有版本，不擅自删除旧文件；小文件压缩通过新 manifest 发布。

## 验证与交付

至少验证重复下载不增行、增加新一天/新分钟、历史补洞、修订冲突、版本回看、区间结束/发布时刻、时区、缺口、0量与缺失量区分、累计量重置、日频数据盘中不可提前使用，以及两期货合约/指数期货的时刻对齐。

给出来源能力表、真实有限样本、字段单位核验证据、完整目录、可运行下载命令、增量更新命令、错误恢复说明、数据质量报告、未支持频率/字段清单。不要宣称来源不具备的秒级 OHLC、历史盘口或真实当时可用时间已满足。

请先做少量真实样本验证，再按我指定范围下载；交付时报告实际写入位置、日期覆盖、代码覆盖、各频率行数和缺失情况。
