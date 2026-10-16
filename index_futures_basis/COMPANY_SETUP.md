# 公司电脑：先看这三步

你已经有 `swhy_delta1\python.exe` 和 Wind 包，**不用新建环境**。

## 第一次使用

1. **确认 App 文件夹。** 公司统一分支 `codex/company-apps` 已包含 `index_futures_basis`，与 `securities_lending` 并排。公司 `D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard` 本身就是仓库根目录，可用 `git rev-parse --show-toplevel` 确认，无需再建一层 dashboard 或重新解压。
2. **告诉 App 你的 Python 在哪里。** 复制 `python.local.txt.example` 为 `python.local.txt`，用记事本打开，只留一行实际的完整路径，例如 `D:\conda\envs\swhy_delta1\python.exe`。不加引号。如果你的路径正好是这个默认路径，可跳过本步。
3. **双击启动。** 先登录 Wind，双击 `start.cmd`。若提示缺少 App 依赖，双击一次 `install.cmd`，完成后重新启动。这会在现有环境补装界面/绘图依赖，不安装或替换 WindPy。

把分红表放进 **`index_futures_basis\inputs`（有 s）**，也可以在界面点「导入分红 Excel」。文件名可用 `基差情况_2026-09-18.xlsx` 或 `指数基差情况_2026-09-18.xlsx`，日期不固定；程序按 **Sheet1 的 B1 日期**选择最新表，读取 G 列分红。

## 以后每天用

- 双击 `start.cmd`：正式模式先显示本地数据，再自动补缺口。第一次下载较多，以后只下载缺少的部分，关闭后数据还在。
- 查询 IC 最远月：点「基差查询」，默认就是 IC / 03 最远月 / 分红调整后年化基差，点「查询」。三个月、六个月、一年的 mean、median、当前百分位在同一张表里。
- 要图：点「图表浏览」→ 选图 →「生成所选图」。要Word：点「报告与记录」→「生成完整 Word 报告」，正式模式会先补齐并校验行情，再生成。当天更新失败默认回退前一交易日，并弹窗及在Word首页写明日期和原因；前一交易日也不完整则停止。生成完双击记录可打开文件夹。
- IH上证50已并列加入各类图表和查询，四个品种各使用00—03四档。升级后会自动增量补齐IH历史数据，复用已有其他品种行情；分红表须含IH00—IH03的G列点数。
- 「图表浏览」中60/90天固定期限各有近3个月、近1个月图；90天固定期限分位用6/12个月，02−00、03−02跨期年化分位用3/6/12个月，并显示当前值和当前百分位。跨期年化按现货分母及两到期日间隔计算，Word附图表和公式说明；查询和CSV窗口一致。
- 有新分红表：放进 `inputs`，再查询/生成即可。无须重新下载行情。
- 应用已开着，收盘后要更新查询/图片：按 **F5**。默认北京时间 **15:05** 后尝试当天日线；生成Word会自行检查更新。旧版默认18:00自动迁移为15:05，其它自定义时间保留，可在设置中查看。

## 拿到后续更新

公司已完成 Git 迁移。保持在 **`codex/company-apps`**，关闭 App，在仓库根目录一次更新所有已发布模块。本机 `data`、`inputs`、`exports`、`config.local.json`、`python.local.txt` 由 Git 忽略规则保留：

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
git status --short
git pull --ff-only
.\index_futures_basis\start.cmd
```

若误切到了开发分支，先执行 `git fetch origin` 和 `git switch codex/company-apps`，成功后再 pull。任何一步报错都停止，保留现场，不强制切换或清理。Git 切换分支会影响整个仓库；切到券单开发分支时，基差可能只剩本地数据文件夹，切回统一分支会恢复源码。源码目录是 **index_futures_basis**（futures 有 s）。

## 遇到问题看这里

| 看到的情况 | 怎么处理 |
| --- | --- |
| 提示 Python 不存在 | 把 `python.local.txt` 改成公司真实路径，一行、不加引号 |
| 缺少 PySide6 / matplotlib 等 | 用 `install.cmd` 补依赖；网络限制导致失败时保留错误信息 |
| 没有 WindPy 或连接失败 | 检查 Wind 已登录，以及指定的 Python 是已装 Wind 包的那个；设置中 Wind Python 留空表示用同一个解释器 |
| 分红为空/公式缓存缺失 | 在 Excel 打开表格，完成计算、保存并关闭，再查询；不要把空白改成零来绕过校验 |
| 表内最新日有多个冲突文件 | 同一目录、同一日期只保留你确认的一份表格 |
| 下载中断/有缺口 | 再按 F5，已成功的批次会复用。错误详情在「数据管理」下方 |
| Wind 历史数据后来修订 | 用「重取指定日期」重取指定范围；普通 F5 不重复下载已有有效数据 |
| 想在家先看看 | 双击 `start_demo.cmd`。界面、图和 Word 都标为合成演示，数值不可用于真实分析 |
| 双击后启动失败 | 查看 `index_futures_basis\data\startup.log`；可用 `python -m index_futures_basis --diagnose` 检查当前解释器 |

Word 由 Python 直接生成，公司电脑生成文件不要求安装 Word；要用 Word 打开和编辑报告，则按公司现有 Office 环境操作。本机已验证离线数据、界面和报告；公司真实 Wind 权限和首次下载需要在公司运行确认。
