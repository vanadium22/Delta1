# 实时行情轮询与保存

`run_realtime.py` 和 `python -m index_strategy.instant_dld` 是同一入口。默认直连内网、验证 TLS，每 5 秒请求一轮，直到 Ctrl+C。请求只获取行情，不提交交易。

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
| `--output-dir` | 模块内 `data` | 自定义保存位置，相对路径按当前工作目录解析 |
| `--max-polls` | `0` | 0 为持续运行，正整数表示有限轮数 |
| `--once` | 关闭 | 只采集一轮，与 `--max-polls` 互斥 |
| `--direct` | 开启 | 不使用环境代理、环境 CA、netrc |
| `--use-env-proxy` | 关闭 | 使用 Requests 的环境设置 |
| `--connect-timeout` | `10` | 建连超时，秒 |
| `--read-timeout` | `30` | 接收数据的读取等待超时，秒；并非整轮总时限 |
| `--ca-bundle` | 公共可信 CA | 指定公司可信 CA 文件，始终验证 TLS |
| `--url` | 当前已验证接口 | 也可由 `SWHY_MARKET_DATA_URL` 提供 |

本机验证中，环境代理模式超时，直连成功。网络或业务失败会记录后继续下一轮，不在同一轮立即重试。Ctrl+C/SIGTERM 会等待当前请求完成或超时，保存摘要后退出。磁盘写入失败会停止采集，防止出现持续请求却没有落盘的情况。

## 保存格式

```text
data/
├── 2026-09-18/<run_id>/batches.jsonl
├── 2026-09-19/<run_id>/batches.jsonl
└── runs/<run_id>/
    ├── run.json       # 初始参数、最终状态、请求数量与状态计数
    └── events.jsonl   # 启动、标的变化、重新加载错误、错过的轮询时点
```

每次启动有独立 `run_id`，不会覆盖上次数据，也不与其他进程共写同一文件。以本机带时区的接收时间按天分目录，每批追加一行并 flush/fsync；正常退出更新摘要。异常断电或强制终止仍可能留下不完整的最后一行，读取时应检查末行，`run.json` 也可能保留 `running`。

`batches.jsonl` 每行包括：

- `schema_version`、`run_id`、`poll`、`batch`、`batch_count`。
- `requested_at`、`received_at`、`elapsed_seconds`、`symbols`。
- `status`、`http_status`（有响应时）、`received_symbols` / `missing_symbols`（业务响应有效时）。
- `response`：完整原始 JSON 结构，行情在 `response.data`，不重命名字段、不转换金额/数量单位、不填补缺失。
- 失败时的 `error` 或非 JSON 响应前 4,000 个字符 `response_preview`。

仅 HTTP 2xx、`respSuccess=true`、无明确失败标志/非零业务代码，且所有请求标的都有非空对象时标记为 `success`。部分标的缺失为 `partial`，全部缺失为 `empty`；业务失败、非 JSON、网络错误分别记录。不会把旧快照补入失败请求；相同行情跨轮出现也会保留，以明确采集时间。

读取示例：

```python
import json
from pathlib import Path

root = Path('index_strategy/instant_dld/data')
for path in sorted(root.glob('*/*/batches.jsonl')):
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            record = json.loads(line)
            if record['status'] in ('success', 'partial'):
                quotes = record['response']['data']
                # 按 record['received_symbols'] 选择本次实际收到的标的。
```

退出码：`0` 为正常完成/停止且已保存的批次全部成功；`2` 为完成但包含部分、空或失败批次；`1` 为配置/本地运行错误。CLI 参数语法错误遵循 argparse，返回 `2`。旧的 `download_market_data.py --direct` 仍可用于单次连接诊断。
