# script_making：本地日报查询

下载两份日报到本机后，通过浏览器查询。默认读取收益互换日报的「存续合约估值」和日报复核表的「簿记要素」，工作表可切换。当前实现下载、读取和筛选；交易新增、提交和审批流程留待后续需求。

## 启动

需要 Python 3.10+ 和 openpyxl。缺少依赖时，在本目录运行 `python -m pip install -r requirements.txt`，然后双击 `start.cmd`，浏览器打开 `http://127.0.0.1:8766`。关闭启动窗口或按 Ctrl+C 停止服务。

端口被占用时运行 `start.cmd --port 8767`。指定 Python 时，将解释器完整路径写入本目录 `python.local.txt`（一行，不带引号）。也可从仓库根目录运行 `python -m script_making.app --open`。服务仅监听本机，不依赖 Node 构建或 CDN。

## 来源路径与保存位置

在「数据与同步」填写共享来源目录和本地保存目录，点击「保存设置」立即生效。共享来源应包含 `YYYY-MM-DD` 子目录，不包含最后一级具体日期。默认保存在本项目的 `data/reports`。

- 设置保存在忽略的 `config.local.json`，配置模板见 [config.example.json](config.example.json)。
- `SCRIPT_MAKING_SOURCE` 和 `SCRIPT_MAKING_DATA` 环境变量可覆盖上述目录；要通过页面修改对应设置，先移除环境变量覆盖。
- 更换保存目录后读取新目录，原文件仍在旧目录，不自动搬移。
- 每个日期目录的 `manifest.json` 记录来源、时间、大小、完整路径和 SHA256。
- 支持在设置中选择已有 Excel 导入，文件名必须保留日期和 `-D1` 后缀。

「同步前一交易日」按北京时间选择**早于今日的最新有效日期文件夹**，下载：

```text
收益互换日报(YYYY-MM-DD)-D1.xlsx
日报复核表(YYYY-MM-DD)-D1.xlsx
```

此规则依赖上游按交易日生成目录，不单独维护交易日历。界面显示实际日期。最新目录缺文件时停止，不静默回退旧日期。网络失败时可继续查询本地数据，访问超过 45 秒停止本次同步。

两份文件先暂存，检查默认工作表、源文件稳定性、大小和 SHA256 后保存。同日期同名但内容不同的已有文件不覆盖，可更换保存目录。重复下载相同文件不重复生成 Excel，并记录共享来源核验。

## 搜索和筛选

- 默认「模糊匹配」支持连续子串和顺序简称。例如「申万」「证投」均可匹配「申万宏源证券投资总部」。
- `/`、逗号、竖线分隔可选词（OR），空格分隔同时需要的词（AND）。多个列条件按 AND 组合。
- 可改用连续包含、精确等于、不等于、为空、不为空。
- 数值列提供范围、大小比较、近似等于、近似零和非零。支持科学计数法、千分位和百分号；`5%` 表示原始数值 `0.05`。
- 默认绝对容差 `ε = 1e-8`，页面可调整。`|x| ≤ ε` 为近似零，`|x| > ε` 为非零，空值不计作零。
- 范围采用 `min - ε ≤ x ≤ max + ε`；大于为 `x > value + ε`，大于等于为 `x ≥ value - ε`。小于对称处理。
- 日期列提供日期区间。支持表头排序、分页、显示列和全部字段详情，详情显示 Excel 原始行号。
- 读取 Excel 保存的缓存值，不调用 Wind 或重新计算公式。使用原始小数筛选，显示格式不影响比较。

## JSON 接口

| 方法与路径 | 用途 |
| --- | --- |
| `GET /api/settings` | 读取本机设置及实际保存目录 |
| `POST /api/settings` | 更新 `source_root`、`data_dir`、`epsilon`，立即生效 |
| `GET /api/catalog` | 本地日期、文件、来源、默认工作表 |
| `POST /api/sync` | 请求体 `{}`，开始后台同步 |
| `GET /api/sync` | 查询 `idle/running/success/error` |
| `GET /api/sheets?kind=swap&date=2026-10-14` | 可用工作表 |
| `POST /api/query` | 查询、排序、分页，返回字段类型及 Excel 行号 |
| `POST /api/import` | 二进制 Excel，`X-Filename` 为 URL 编码后的原文件名 |

JSON 请求使用 `Content-Type: application/json`。`kind` 为 `swap` 或 `review`。不传 `sheet` 时使用默认工作表。列 ID 从查询响应的 `columns` 获取，不能依赖任意列名对应固定位置。

```json
{
  "kind": "swap",
  "date": "2026-10-14",
  "sheet": "存续合约估值",
  "filters": [
    {"column": "c2", "op": "fuzzy", "value": "证投"},
    {"column": "c14", "op": "range", "min": "5000", "max": "10000"}
  ],
  "epsilon": 1e-8,
  "sort": {"column": "c14", "direction": "desc"},
  "page": 1,
  "page_size": 50
}
```

文本操作：`fuzzy/contains/eq/ne/blank/not_blank`。数值：`range/gt/gte/lt/lte/eq/ne/zero/nonzero/blank/not_blank`。日期：`range/eq/gte/lte/blank/not_blank`。`search` 为全字段关键词，每页最多 200 条，最多 30 个条件。错误返回 HTTP 400 和错误信息，跨站访问返回 403。

## 公司更新与验证

公司保持 `codex/company-apps`，关闭 App，在仓库根目录运行：

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
git pull --ff-only
```

然后运行 `script_making\start.cmd`。首次使用需在页面配置共享来源；本机设置和原始数据不通过 Git 同步。

离线测试（从仓库根目录）：

```powershell
python -m unittest discover -s script_making/tests -v
```

测试使用合成 Excel 和本机临时目录。实际公司共享盘验证状态见 [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md)。

正式源码、测试和无真实数据的配置模板进入 Git。`materials` 原始文件、`data`、`cache`、导出和 `*.local.*` 保留本机。开发与交付遵循 [AGENTS.md](AGENTS.md)。
