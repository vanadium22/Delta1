# 标准数据契约与路径选择

本规范用于离线回测。输入只读，不下载、不连接 DDB/VPN，不读取 Z 盘、已知 `backfilled_cn_index*` 混合缓存及其派生试跑。切换数据位置只修改 `data` 配置；标准输入和旧注册分片均适配为 `MarketData`，因子/CTA 不持有业务路径。

## 数据位置与用途

2026-11-02 已核对现有活动 manifest，未搬动、复制或删除真实数据。本机完整绝对路径清单保存在忽略目录 `local_artifacts/validation/2026-11-02/framework/data_inventory.local.json`。

| 类型 | 现有位置/入口 | 规则 |
|---|---|---|
| 正式本地行情 | 旧项目 `data/market/index_futures/dashboard/normalized/cn_index`、`cn_index_future` | 纯来源 `shared_ddb_wind_csmar_v2`；312 个日线日期，2025-07-01—2026-10-14；通过 manifest 读取 |
| 合约参考 | 旧项目 `dashboard/localsetting/contract_reference/current.json` | 已有 84 个挂牌/到期参考；JSON 适配器保留，不猜交割日 |
| 已知排除缓存 | 同层 `backfilled_cn_index`、`backfilled_cn_index_future`；旧混合试跑目录 | 路径和来源标签均拦截；位于 P 盘也不能使用 |
| 原应用分红缓存/配置 | 旧项目 `data/dividends/index_futures/inputs`、本工作区 `dashboard/localsetting/numeric_excel/native.json` | 保留原位；native 原路径选择指向混合缓存，不再由桌面预选 |
| 合成/单元输入 | `dashboard/backtest/test`、`synthetic.py` | 代码生成；仅验证框架，不能补真实历史 |
| 中间结果 | 指定输出目录中的 `factor/`、`cta/`；旧 carry 目录中的因子表/映射/输入审计快照 | 不参与默认行情发现；新阶段可分别保存、校验、加载 |
| 回测输出 | `outputs/backtest/` 或显式 `--output`，每次新目录 | 账户/权益/持仓/成交/指令/元数据；不回写数据源 |
| 开发验证 | `local_artifacts/validation/<日期>/` | 忽略的合成输入、验证报告、截图，不发布真实材料 |

此前路径规则：桌面依次尝试 `native.json`、`app/native.json`、`numeric_excel/native.json`；读取器无明确源时读取 native 路径，再尝试工作区 `data`；根目录发现先检查 `backfilled_*` 再检查纯 `cn_*`，候选有来源校验。显式混合 native 不会自动改选其他集。因子日频按 daily→generic close→minute 选择，自动频率按 minute→generic→daily；执行入口对 generic 和双频表另有兼容判断。这些多处选择已收束到 `DataConfig` 和适配器。

## 当前唯一配置入口

复制 [宽表模板](config.example.json) 或 [注册行情模板](registered.config.example.json) 为本机 `.local.json`。

- `data_root` 在 JSON 中相对于配置文件；其余数据路径相对于 `data_root`，没有根目录时相对于配置文件。Python 直接构造 `DataConfig` 时，没有根目录的相对路径以工作目录为准。
- 宽表用 `daily_close_path` 和可选 `minute_close_path`；旧单表用 `close_path`。两种方式不能混用，也不能与 `history_roots` 混用。同一文件不能同时声明日线和分钟。
- 注册源可显式列出 `history_roots`。只给 `data_root` 时，仅发现该根下 `market/index_futures/dashboard/normalized/cn_index` 和 `cn_index_future`。不扫描其他盘、测试目录、缓存、输出或备份。
- `dashboard_config_path` 是主动指定的旧配置适配器，只读白名单路径；不与显式行情路径并用。不再隐含查找任何 native 配置。
- `dataset_id/data_version/source_id` 声明宽表身份；实际文件另记绝对路径、SHA256 和大小。注册集以 `history_versions: {目录: 32位版本ID}` 固定 manifest；空对象表示在读取时冻结 current 并记录实际版本。相同根目录的保存因子经 CTA 到执行时会沿用冻结版本，显式冲突版本报错。
- 同一标的/频率/日期出现在多个注册根时拒绝。来源标签含已知 Z 派生标记时，在读取分片之前拒绝。
- 桌面“本轮实际数据清单”、CLI 输出和阶段/回测元数据展示最终绝对路径、版本、覆盖；有缺口仍由实际持仓单元校验，不以首尾日期冒称全覆盖。宽表在因子计算后被原位修改，阶段执行检测 SHA 变化并拒绝保存结果。

桌面保存时，根目录内的文件继续保存为相对位置；重新打开后只改根目录即可重定位。文件在根目录外时保留绝对路径。

## 标准表

推荐 Parquet，保存带时区的 `DatetimeIndex(name="timestamp")`。兼容 CSV/TSV/Feather 的时间列 `timestamp/date/datetime/event_time`；pickle 仅在 `trusted_pickle=true` 时读取。日线/分钟/参数宽表必须是数值矩阵，引用表是记录表。

| 输入 | 字段/维度 | 单位和校验 |
|---|---|---|
| 日线 close | 时间戳 × 实际期货/指数 | 原始未复权指数点，正数或 NaN；每日最多一个实际收盘时间 |
| 分钟 close | 时间戳 × 实际期货/指数 | 原始 close；保留真实时刻，不能用调整价成交 |
| 合约参考 | `instrument_id, root, listing_date, expiry_date`，可选 `multiplier, known_at` | 实际代码如 `IC2612.CFE`，日期 ISO；挂牌≤到期。Parquet/CSV/TSV 标准表四字段必备；旧 JSON `contracts` 记录兼容仅到期等历史输入，连续生成仍要求完整日期 |
| 乘数 | 可选生效时刻 × 实际合约，或 `multipliers` 显式映射 | 元/点/手；表独占，不与固定覆盖并用。固定值优先级：显式实际代码→显式品种→参考表实际代码→内置 IF/IH=300、IC/IM=200。现货恒为 1 |
| 保证金率 | 生效时刻 × 实际合约，或 `margin_rates` 固定映射 | 小数比例 `(0,1]`。二选一，无源不猜。新模板明确 IF/IH/IC/IM=1.0，即 100%；历史 15% 情景仍可显式指定 |
| 剩余自然日 T | 可选日期 × 实际合约 | 整数自然日；由真实到期日减上海当地日期得到，不是交易日。独立输入与到期参考同时有值时须完全一致，不沿用昨日 T |
| 分红点数 | 可选日期/时刻 × 实际合约，或版本记录 | 到期前剩余分红，指数点、非负；明确 0 有效，缺失不能补 0 |
| 交易日历 | 可选 CSV `trade_date/date/timestamp`，或 JSON `trading_days` | 唯一日期序列；完整交易日缺口审计应显式提供，否则只采用观测日期 |

指数代码统一映射：`000300.SH→IF_spot`、`000016.SH→IH_spot`、`000905.SH→IC_spot`、`000852.SH→IM_spot`。映射后列名重复拒绝；价格输入不能使用 00—03 连续别名。

## 时间、重复和缺失

- 无时区日期/时间按 Asia/Shanghai 解释；带时区时间转换为上海时间。数值 epoch 没有明确单位时拒绝，标准文件应直接存带时区时间。
- 日线午夜日期标签，包括上海时区的午夜，按 `data.daily_label_time="15:00"` 转为收盘标签；显式非午夜时刻保留。分钟输入不将午夜改写为收盘。指令日期标签单独由 `backtest.date_at` 解释，日频执行仍采用收盘信号规则。
- 宽表在时区/指数映射/日期转换后重复的记录均拒绝。注册源同一修订键值冲突拒绝；合法历史修订在冻结 manifest 中选择最大 revision，不合并两个来源的重复 bar。
- 原始成交价格不前填、不后填、不插值。独立日线优先；同一真实时间可使用实际分钟观察，无日线时取该日最后真实分钟并保留时间；无分钟时在真实日线 close 成交。必要的持仓估值缺价报错。
- 保证金/乘数采用“生效时刻起直到下个版本”的整行参数语义：只向后沿用，不倒填、不跨列借值；新版本显式 NaN 持续未知，不复活旧值。乘数持仓期间变化报错。
- 日历中的完整缺失日保持缺失。因子历史统计排除当前整日；除年化中已知 T 太小的明确排除外，缺数不缩短窗口。

## 分红可选研究输入

执行盈亏始终来自 raw close。`data.dividend_mode="required"` 让需要 D 的因子要求明确输入；`"ignore"` 明确假设 D=0，并与任何分红文件、版本库、快照情景互斥。原价分位和跨期价差分位不依赖 D。

版本 JSON 使用 `records` 数组，字段 `contract_id, points, effective_from, revision, source_business_date`；`points` 为剩余指数点，`effective_from` 为带时区生效时刻。只能用当前时刻之前已生效的版本，新记录不回写过去。既有 `DatedDividendBook` 的明确零及前序到期合约估计仍保留来源/版本。日期宽表明确视为当天已知的研究输入，仅同日使用，不填其他日期；需要盘中生效审计时应使用版本记录。未知发布时间不能声称 PIT。

旧 `adjusted_close_path` 适配器从显式 F+D 与 raw F 的差计算 D；旧单快照 `asof_snapshot/fixed_scenario` 保留并标明局限。它们不成为交易价格，也不能代替完整历史 D。

最小可运行输入通过 `python -m dashboard.backtest.synthetic --output <不存在的新目录>` 创建；四品种日线、少量分钟、合约 Parquet 和本机配置全部是合成夹具。分阶段调用见 [WORKFLOW](WORKFLOW.md)。
