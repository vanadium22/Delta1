# 旧网页预览存档 · 非默认国内指数 App

2026-10-01：本文记录旧实现。现在 `start_dashboard.cmd` 和 `python -m dashboard` 均启动原生国内指数 App；下文原来的启动命令已改为显式旧预览入口。旧配置不适用本版新数据源，默认不会启动或读取。

2026-09-30 范围更新：下一步原生 Windows App 仅面向国内 A 股指数及 IF/IH/IC/IM 股指期货，历史数据未来重新下载。新增数据格式、增量读写基础与下载任务 Prompt 见 [data_contract/README.md](data_contract/README.md)；它们尚未接入下文的旧网页预览，也没有绑定已有其他市场历史库。下文记录的是先前初版的实际功能。

独立的本机 Web App，覆盖期货、指数、ETF、股票。读取已有行情库，也可以从页面调用原采集模块；公式与结果由看板自己管理。

## 打开

如需维护旧实现，在明确选择的旧预览入口运行后，浏览器进入 <http://127.0.0.1:8768>。

也可以在 `P:\project\swhy\Delta1\project` 执行：

```powershell
& 'P:\code_content\python_work_env\conda_env\swhy_delta1\python.exe' -B -s -m dashboard.web_preview --open
```

复用当前环境的 Python、pandas、pyarrow、requests；前端为本地 HTML/CSS/JavaScript，无 CDN 或 npm 构建步骤。启动脚本支持用环境变量 `SWHY_DELTA1_PYTHON` 指定其他已配置好的 Python。

本次运行配置指向 `dashboard/runtime/market` 的真实接口测试数据。打开页面不会自动开始采集。「数据与任务」可以选择已有行情根目录、修改结果目录，或者开始采集 / 采集一轮 / 停止。关闭浏览器不停止服务或采集；使用页面底部「停止看板服务并归档」或服务窗口 Ctrl+C 正常退出。

如果删除本机配置，代码的默认行情目录沿用采集模块的 `Z:\Project_data\realtime_market`。读取该目录需要现有权限；无法读取时页面显示具体错误。采集失败同样会显示日志。

## 页面和已完成能力

| 页面 | 当前能力 |
| --- | --- |
| 市场总览 | 四个指数卡片，跨资产行情搜索与筛选，按实际合约去重，真实采样轨迹、盘口详情、IC 期限结构、自定义指标卡片 |
| 期货结构 | IF/IH/IC/IM 切换，四个到期月份，六组跨期组合，两侧盘口价差，别名与实际合约身份 |
| 公式中心 | 从模板编辑 Python 和 JSON 参数，当前数据试算，发布、启停、版本保留；新指标自动加入总览 |
| 结果与回放 | 按结果分区日期查询最近 250 条计算记录，查看输入代码、具体合约、序号、采集时间及公式版本，手动发布 Parquet |
| 数据与任务 | 修改行情 / 结果路径、订阅代码、采集间隔、过期阈值及两腿接收时间误差；管理本看板发起的采集任务 |

内置模板：跨期价差、期现基差、一档盘口不平衡、相对最近 N 条采样均值的价格偏离。本次另通过页面发布了「黄金盘口价差」，作为完整操作示例。

当前「回放」是回看已保存记录，不会重新执行历史回测。尚未做拖拽布局、提醒推送、完整异常事件引擎、ETF 申赎/IOPV 定价、分红和融资成本模型、历史分钟线重采样。

## 模块边界

```text
dashboard/                     看板自己的界面、服务、配置、公式、结果库
  gateway.py                   调用 RealtimeReader / collect / MarketDataClient
  service.py                   读取与公式调度、配置、输入检查
  formula_worker.py            受限 Python 子进程
  results.py                   计算结果 SQLite 与按日 Parquet
  static/                      本地前端

index_strategy/instant_dld/     独立行情采集模块
  contract_aliases.py           本次新增的可选合约别名与双身份保存扩展
  collector.py / client.py      继续使用已有轮询和接口请求
  realtime_store.py / reader.py 继续使用已有持久化和读取接口
```

看板不复制轮询、行情归一化或实时库实现。新扩展可由其他采集入口独立调用；原采集桌面入口不会因为打开看板而自动改变行为。

看板直接调用采集模块时，组合 `ExpiryAliasResolver` 与 `DualIdentityStore`。采集模块没有依赖看板代码。外部采集器已经写入的行情可由看板只读使用；看板的停止按钮只管理自己启动的任务。

## 合约输入和双份保存

| 输入 | 本版行为 |
| --- | --- |
| `IC00.CFE` / `IC01.CFE` / `IC02.CFE` / `IC03.CFE` | 本地约定为按到期排序的第一至第四个股指合约；IF/IH/IM 同理。不是供应商原生连续合约代码的声明 |
| `IC2610.CFE` 等具体合约 | 直接请求和保存；接口无数据就保留失败 / 缺失信息 |
| `AU.SHF` | 使用原主力映射表解析具体合约；要求有对应已完成交易日的映射 |
| `AU01.SHF` 等商品两位月份别名 | 明确报错：尚未定义“固定 1 月”还是“次近月”；目前请用具体合约或已有主力映射 |
| `IC.CFE` 等股指主力标识 | 仍需要主力表；没有可靠映射就不自动认定主力 |
| `510300.SH` / `000905.SH` 等 | 按各自完整代码保存 |

2026-09-29 实测：四个股指品种的具体月份均为 `2610、2611、2612、2703`；`IC00.CFE → IC2610.CFE`、`IC01.CFE → IC2611.CFE`。AU 主力表映射为 `AU2612.SHF`，夜盘对应本地解析交易日 2026-09-30。

合约候选由交易日历及到期规则生成，每轮采集请求具体代码，并按接口返回记录有无行情；规则候选不是交易所每日挂牌文件。别名换月后不会把昨日旧合约误用为新合约。日历覆盖到期日不足时明确报错，需更新日历。

一次请求 `IC00.CFE` 会同时写入 `IC00.CFE` 与 `IC2610.CFE` 的记录；`AU.SHF` 同理写入 AU 别名和实际合约。若用户同时订阅两者，同一批次不重复写实际合约。它们是同一笔观测的不同身份，成交量不能相加。默认行情表按实际合约去重。

## 数据位置和字段

本次预览的实际目录：

```text
P:\project\swhy\Delta1\project\dashboard\
  localsetting\dashboard.json                看板路径与订阅等本机配置
  localsetting\formulas.json                 当前启用和停用的公式
  localsetting\formula_versions\<id>\<版本>.json
  runtime\market\                           本次真实接口采样数据
    raw\...                                 原始响应与请求记录
    live\quotes.sqlite3                     采集模块实时库
    data\<代码>\...                         各代码的 Parquet 分片
  runtime\results\                          独立看板结果根目录
    dashboard_live\results.sqlite3          实时计算记录与分片目录
    formulas\<id>\<版本>.json                与结果一起保存的完整公式 / 参数
    factors\<id>\<版本>\年\月\日期.<摘要>.parquet
```

实际合约和别名都有各自的行情目录。结果先提交 SQLite，再在首次有结果、每分钟、点击归档或正常退出时发布不可变 Parquet 分片。每个分片用临时文件原子发布，随后登记到 SQLite。结果根目录需要支持本机文件锁与 SQLite，明确拒绝 Windows 网络共享盘。

切换结果目录只影响新的计算，旧文件保留；页面记录旧目录。若要查询旧目录，停止本看板采集后，把结果路径改回对应目录即可。配置、公式、行情与结果分开保存；运行目录和本机配置不纳入 Git。

行情标准化后可供公式使用的主要字段：

| 字段 | 含义 |
| --- | --- |
| `symbol` / `source_symbol` | 用户输入身份 / 实际请求合约 |
| `sequence` | 实时库递增序号，支持追溯 |
| `timestamp` | 采集接收时间，标准化到秒；接口中不是完整交易所时间戳 |
| `quote_time` | 接口返回的时分秒，缺少完整行情日期 |
| `trading_date` / `mapping_date` | 由本地日历解析的期货交易日 / 主力映射数据日期 |
| `close` | 接口最新价，不是交易日收盘价 |
| `volume_total` | 来源累计成交数量，保持来源单位 |
| `volume` / `volume_start` / `volume_interval_seconds` | 连续有效采样之间的累计量差及接收区间，不是固定 1 秒成交量 |
| `bid_price_1`…`5` / `ask_price_1`…`5` | 买卖盘口价格；无效价格和缺失哨兵转换为 `None` |
| `bid_volume_1`…`5` / `ask_volume_1`…`5` | 买卖盘口数量，保持来源单位 |
| `quality_flags` | 原采集模块的数据质量位标记 |
| `mid` / `spread` | 有效买卖一档的中间价 / 买卖价差；无有效盘口则 `None` |

本次接口实测通常为股指 / 黄金一档有效、ETF / 股票五档有效、指数盘口不可用。接口原始数据的其余字段仍保留在 raw 中；本版未把未核实的结算价尺度、零持仓量拿来计算主力或收益率。51 个原始返回字段及此前逐代码测试见 `analysis/2026-09-29/看板与行情采集分析.md` 和同目录证据文件。

看板结果包含 `factor_id、version、name、calculated_at、trade_date、quality、unit、values_json、inputs_json`。`inputs_json` 保留每个输入的序号、实际代码、采集时间、源时分秒、交易日和映射日。期货按本地解析交易日分区；没有交易日的指数、ETF、股票按北京时间采集日期分区。跨日期输入会单独标记。

每次看到新采样记录，后台计算并保存一份结果；多次刷新相同采样不会重复写入。价格相同的新采样仍是新观测。后台约每 2 秒读取一次，不承诺逐笔无遗漏：若采集快于计算，可只计算最新一帧。单个公式失败不会停止其他公式。

## 添加公式

到「公式中心」选择模板，修改 ID、名称、输入代码、参数和代码，点击试算，然后发布。相同 ID 发布为新版本；变更代码、参数、输入或单位会改变版本号。启用公式的输入会自动并入本看板的采集清单，运行中的采集器下一轮重新加载；外部采集器的订阅仍由外部管理。

```python
def compute(quotes, history, params):
    near = quotes[params["near"]]
    far = quotes[params["far"]]
    if near["mid"] is None or far["mid"] is None:
        return {"跨期价差": None}
    return {"跨期价差": near["mid"] - far["mid"]}
```

参数示例 `{"near":"IC00.CFE","far":"IC01.CFE"}`，输入代码填 `IC00.CFE, IC01.CFE`，单位填 `点`。输出字典的键就是指标名称，一个公式可返回 1–20 个数值或 `None`，并共用一个单位。

`history[代码]` 是按采集顺序排列、同实际合约和同结果日期的最近最多 300 条样本。它不是等间隔 K 线。`sma(history[代码], "close", 20)` 要求最后 20 条均有值，否则返回 `None`；窗口大小为 1–300。页面总览显示公式第一项，试算及保存记录保留全部输出。

支持局部赋值、`if`、四则运算、条件表达式、字典 / 列表索引，以及 `abs、min、max、round、sum、len、mean、stdev、sqrt、log、sma`。不支持 import、属性调用、循环、递归、文件或网络操作。每个公式独立子进程、最长 3 秒，并检查代码长度、输入体积、数值范围与输出；这是本机研究模板接口，不是通用任意 Python 执行环境。

发布后的代码和参数保留在版本文件，并随首次结果复制到结果根目录。编辑器内容在发布前只存在页面中，刷新会丢失，当前尚无另存草稿按钮。

## 时间与价格口径

上游只有时分秒，不能据此认证交易所行情日期。本版始终明确标记「时间未核验」「休市缓存」或「历史 / 过期」。交易时段判断是时钟提示，不是完整节假日开闭市判定。两腿接收时间超出设置误差时停止计算该公式；同批次收到两个缓存报价也不等于它们在交易所同步。

跨期买入观察价差 = 近月卖一 − 远月买一；卖出观察价差 = 近月买一 − 远月卖一。费用、冲击和真实可成交量未纳入。期现基差模板为期货最新价 − 指数，不是完整套利定价。首页「观察期变化」使用最近采样窗口的首尾价格，不是日涨跌幅。

## 本次验证

- 20 项看板测试：公式计算 / 非法代码 / 子进程超时、输入对齐、换月、双身份读回、结果持久化、路径切换、公式版本、订阅更新、重复启动和本机接口边界。
- 原采集模块 31 项合约测试、54 项实时数据测试通过。
- 真实接口 25 轮：26 个实际标的，含别名每轮 43 行，共 1,075 行；IC00 / IC01、AU 主力及其实际合约、ETF 均从 Parquet 读回成功。证据：`runtime/live_validation.json`。
- Edge 浏览器完成真实数据展示、筛选、四月份与六组价差、公式失败恢复 / 发布 / 启停 / 页面重载、结果详情和桌面 / 窄屏布局验证。证据：`runtime/browser_validation.json`，截图：`runtime/screenshots/`。

测试命令（从 `project` 目录）：

```powershell
& 'P:\code_content\python_work_env\conda_env\swhy_delta1\python.exe' -B -s -m unittest tests.test_dashboard
& 'P:\code_content\python_work_env\conda_env\swhy_delta1\python.exe' -B -s -m unittest discover -s tests -p 'test_contract*.py'
& 'P:\code_content\python_work_env\conda_env\swhy_delta1\python.exe' -B -s -m unittest discover -s tests -p 'test_realtime*.py'
```
