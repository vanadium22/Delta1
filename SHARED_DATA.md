# Delta1 公共本地数据（接口 v1）

三个 App 共用仓库根目录下的 `data`，默认导出到 `outputs/<模块>`。目录由模块位置解析，与启动工作目录无关；无网络调用、无额外服务或新依赖。真实数据、本机配置、原始材料及输出均不进入 Git。

## 配置与目录

默认 `data_root=data`、`outputs_root=outputs`。可复制 `config/examples/data.example.json` 到忽略的 `localsetting/data.local.json`。相对路径相对于仓库根目录；支持绝对路径。`DELTA1_DATA_ROOT`、`DELTA1_OUTPUTS_ROOT` 优先于本机配置。每个 worktree 默认独立；希望复用真实数据时为该 worktree 配置同一绝对数据根目录。测试必须指定隔离根目录，不能指向生产数据。

模块配置中的 `@shared` 表示公共默认目录。原默认值（基差 `data/inputs/input/exports`，日报 `data/reports`）兼容解析到公共位置；显式自定义路径继续受支持。公司使用自身仓库的 `data`，不写死家里盘符。

```text
data/
  market/index_futures/wind/market.sqlite
  market/index_futures/offline/market.sqlite
  dividends/index_futures/inputs/             当前可选的原始分红 Excel
  dividends/index_futures/archive/            SHA256 版本归档
  reports/swap/YYYY-MM-DD/                    两份日报、manifest.json
  lending/live/YYYY-MM-DD/snapshots/<批次>/    完整券单
  lending/live/YYYY-MM-DD/latest.json
  reference/industry/YYYY-MM-DD/              Wind 行业缓存
  templates/script_making/                    已有 Excel 模板副本
  demo/<模块>/                               演示数据、独立配置
  cache/market/<数据集>/<来源>/<频率>/<交易日>/  明确可清理的实时缓存
  _catalog/                                  数据集接口和位置登记
  _migrations/                               复制校验清单（包含原位置）
outputs/<模块>/                              新导出
```

## 升级与迁移

公司关闭 App，在公司统一分支执行 `git pull --ff-only`。各 App 首次启动会复制旧默认目录中的运行输入，核验成功后使用新位置；旧文件及旧配置原样保留。成功标记后不再扫描旧目录，后续新分红放公共目录或使用 App 导入。旧目录不可作为新数据更新入口。

迁移使用文件哈希核验，SQLite 使用备份 API（包含已提交 WAL 内容）并核对逻辑内容和完整性。目标已有不同内容时明确报错，保留双方，不覆盖。券单及日报清单改存相对于各自数据集根目录的 `relative_path`；已有界面/API 继续返回解析后的绝对 `path`。源共享盘路径、数据日期、原下载时间、哈希及失败状态保留。

不迁移 QA、旧材料脚本、临时文件；原始模板/日报材料保留。历史基差导出仍可在记录页访问，新导出进入公共 outputs。正式、离线和演示库保持独立，不用演示补正式数据。

在仓库根目录可先查看计划，再执行：

```powershell
python -m shared_data paths
python -m shared_data migrate
python -m shared_data migrate --apply
python -m shared_data catalog
```

默认不访问 Wind 或共享盘。数据搬迁不改变增量补缺、日线截止时间、分红假设、日报选择规则或当日券单复用；最新股票价格仍由现有流程实时请求。遇到源库正在更新应关闭对应 App 后重试。

## 公共读取

```python
from pathlib import Path
from shared_data import DataPaths, Catalog
from shared_data.readers import LocalData

paths = DataPaths.for_repo(Path(__file__).resolve().parent)
data = LocalData(paths)
quotes = data.daily_quotes("2026-10-01", "2026-10-15",
                          codes=["IF2610.CFE"], fields=["close", "oi"])
report = data.report_file("swap", "2026-10-14")
dividends = data.dividend_files()
inventory = data.lending_files("2026-10-14")
```

读取接口不下载、不造缺失数据库、不填充缺失行情。日线结果含 `api_version=1`、`frequency=1d`、时区、数据模式及原始记录。分红选择/Excel 解析/库存计算继续由现有业务模块负责。只读行情保留实际合约代码；连续档位需配合库内 mapping/contracts/calendar，不得将连续代码当实际合约。

## 看板、实时缓存与分钟历史

用 `Dataset(name, source, frequency, mode, storage, retention, keep_days, schema_version)` 登记数据集。数据集标识由名称、来源、频率、模式组成；不同频率、不同来源和合成模式不可混用。登记后契约或位置变化需明确迁移，不能静默覆盖。

```python
from shared_data import Catalog, Dataset
from shared_data.io import file_lock

catalog = Catalog(paths)
minute = Dataset("indices", "wind", "1m", storage="parquet")  # 默认永久历史
realtime = Dataset("indices", "feed", "tick", retention="daily_cache", keep_days=2)
catalog.register(minute)
catalog.register(realtime)
historical_folder = catalog.partition(minute.key, "2026-10-16", "000300.SH")
cache_folder = catalog.partition(realtime.key, "2026-10-16")
_, cache_root = catalog.get(realtime.key)
with file_lock(cache_root / ".writer.lock"):
    # 写入临时文件，校验后原子发布；发布文件才可供其他模块读取。
    pass
available = catalog.partitions(minute.key, "2026-10-01", "2026-10-16")
plan = catalog.prune(realtime.key)  # 默认只预览
```

分钟历史采用按交易日/标的分区的持久化 Parquet 等格式，不进入实时清理目录。实时缓存明确指定 `daily_cache` 与 `keep_days` 后才允许清理；保留天数按北京时间自然日计，包含当天，未来日期不清理。清理持有同一数据集写锁，拒绝历史数据集、越界路径及链接目录。当前三个 App 不自动清理任何数据；看板接入时在其日常维护流程调用清理，可先预览 `python -m shared_data prune <数据集标识>`，显式 `--apply` 才删除已过期缓存分区。

后续行情适配器须明确：`trade_date` 为交易日，`event_time` 为带时区的行情时间，`received_at` 为采集时间；不能用采集日期替代交易日。注明价格/成交量/成交额/持仓量的单位、分钟 bar 的起止与时间标签、累计或区间成交量口径、调整方式、主键及重复/修订处理。采集器可保留数据商原始字段，但应发布具有 schema_version 的标准视图。永久历史的缺口按标的/频率/交易日或时间范围补齐，实时快照不能直接冒充分钟 OHLC。

此版本提供目录、数据集登记、日期分区、只读适配及缓存生命周期接口；看板本身、实时采集器和分钟下载器待其接入时实现。

## 验证

```powershell
python -m unittest discover -s shared_data/tests -v
```

公共测试覆盖路径隔离、环境配置、便携清单、原件保留、冲突拒绝、WAL 备份、迁移幂等、只读访问、频率隔离、历史不可清理、当日缓存保留与进程锁。各 App 的读取及原业务回归记录在其 PROJECT_HANDOFF.md；公司汇总验证见 COMPANY_SYNC.md。
