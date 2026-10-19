# 公司 Wind 诊断：运行后复制结果

先关闭股指基差 App，登录公司 Wind 终端。沿用已经配置好的 Python / Wind 环境，不用重建环境。

## 直接运行

在公司 PowerShell 中复制：

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
git pull --ff-only
.\index_futures_basis\diagnose_wind.cmd
```

也可更新后直接双击 `index_futures_basis\diagnose_wind.cmd`。入口复用原 App 的解释器选择，以及设置中的 `wind_python`、合约映射字段和到期日字段；使用有控制台的 Python，结束后等待按键，便于查看结果。

通常需要约1—3分钟；默认单批请求最多等待25秒，联网诊断总预算180秒，超时后停止继续连接，保留已完成的证据和错误。预算不含少量文件保存与进程清理时间。

## 复制结果给我

结束时控制台会打印实际结果路径。默认目录在项目根目录：

```text
data\diagnostics\index_futures_basis\
  latest.txt                         最近一次可复制结果
  latest.json                        最近一次结果目录指针
  YYYYMMDD_HHMMSS_批次\
    可复制.txt                       本次完整可复制结果
    diagnostic.json                  本次完整结构化证据
    probe.sqlite                     本次独立行情测试库，留本机
```

最方便的方式：保持在项目根目录，运行下列命令将结果复制到剪贴板，然后直接粘贴到聊天：

```powershell
Get-Content -LiteralPath '.\data\diagnostics\index_futures_basis\latest.txt' -Raw -Encoding UTF8 | Set-Clipboard
```

也可以打开本次 `可复制.txt`，按 Ctrl+A、Ctrl+C，再粘贴给我。**有FAIL或SKIP也复制整份内容**，不要只抄最后一句错误。如果配置了自定义公共数据目录，以控制台打印的实际路径为准。

报告记录程序提交号、App/实际Wind解释器、WindPy位置、日历参数、调用日期范围、返回字段/列数/长度及少量日期样本、错误码、失败堆栈、请求耗时和补缺结果。文本/JSON不输出行情价格或持仓值，不查询账户信息或完整转储本机配置；独立SQLite测试库留在本机。

2026-10-19第二轮公司反馈已确认8项全部通过，源码版本为 `320a332`，反馈提交为 `d4325d6`。第一轮的90天全零已定位到日历参数：同样使用YYYYMMDD和Days=Trading，CFFE返回零，CFFEX返回58个日期，且计数一致。故当前首选 `TradingCalendar=CFFEX;Days=Trading` + YYYYMMDD；之前依据旧手册首选CFFE的修改不适用于公司环境。日志未单独测试CFFEX配ISO日期，不能将日期格式本身认定为根因。

实际验证内容：10月17—18日周末、10月7日节假日均正常零交易日；IF/IC/IM/IH的10月16日行情首次38批补齐，缺失字段为0；重复检查0次请求；人为在独立库移除一格IF持仓后，仅1次请求补回。43次诊断请求全部成功，正式库仍只读。

新版 `raw.attempts` 记录每组实际发送的日期格式、CFFE/CFFEX参数和原始返回，`selected: true` 标出经过校验采用的一组。长期全空时额外输出默认日历、SSE及自然日对照，**对照只用于定位问题，不用于期货同步**。日历未恢复时，周末/节假日检查显示SKIP；不要把终端“已连接”当作日历服务正常。

Wind官方包装源码会把date/datetime对象转换为YYYYMMDD；当前同时采用公司已实测成功的这一格式。源码依据见 [Wind官方WindPy.py](https://github.com/WindQuant/Official/blob/master/WAPIWrapper/WAPIWrapperPython/WindPy.py) 的tdays/tdayscount实现；本次日历参数结论以公司实测对照为依据。

## 检查内容与结果含义

| 检查 | 通过表示 |
| --- | --- |
| Python / WindPy / 终端连接 | 实际Wind解释器可以加载WindPy并连接终端 |
| 正式本地库概况 | 只读检查实际正式库路径、记录数、各品种最新日期及日历校验版本；没有库时会明确显示 |
| 近期90天日历 | 中金所日历返回有效日期，日期序列与TDAYSCOUNT数量一致，并记录实际成功参数 |
| 最近完整周末 | 周边日历健康且Wind确认零交易日；健康检查失败时本项SKIP |
| 休市工作日样例 | 从已验证日历中寻找工作日休市样例，并再次核验零交易日；不靠周一至周五猜节假日 |
| 独立库首次补齐 | 使用App相同同步算法，实际取得最近一个已完成交易日的IF/IC/IM/IH四品种、00—03映射、到期日、收盘价及持仓 |
| 重复检查 | 数据完整后再次查询，零额外行情请求 |
| 单字段补缺 | 仅在独立库移除一个IF当月合约的持仓值，重跑时只补该单元格，其余行情保持不变 |

`PASS`=该项通过；`FAIL`=该项失败，查看随后的错误与原始结构；`SKIP`=前置条件未满足或未找到样例，尚未验证，不能当成通过。完整执行后仍可能有FAIL，报告照常生成。命令退出码0表示全部通过，2表示存在失败或未覆盖项，1通常是解释器/命令启动失败。

诊断中的“行情补齐”发生在新建的 `probe.sqlite`，**不会修改正式行情库**，也不清理已有数据。正式库的实际增量更新仍在 App 中点击“检查并补齐行情”或按F5。

本轮已全部通过，无需为了确认同一结果反复运行诊断。公司更新后重启App，在“数据管理”点击“检查并补齐行情”来更新正式库；不需要把probe.sqlite复制或覆盖到正式库。诊断当时为10月19日11:15，早于App默认15:05截止，最新已完成交易日为10月16日；10月19日收盘后再尝试当天行情。

## 需要复现指定日期时

可指定历史截止日和一个工作日休市样例。下面以2026年国庆期间为例，是否休市仍由Wind结果核验：

```powershell
.\index_futures_basis\diagnose_wind.cmd --as-of 2026-10-16 --holiday-date 2026-10-01
```

截止日不能晚于App当前已收盘截止日（默认北京时间15:05之前取前一自然日，再按Wind日历选最近交易日）。如果90天内没有休市工作日，报告会SKIP该项，可用 `--holiday-date` 补测。

不需要结束后等待按键、需要保存到指定父目录时：

```powershell
.\index_futures_basis\diagnose_wind.cmd --no-pause --output '.\data\diagnostics\wind_check'
```

如果已激活正确Python环境，也可以直接运行：

```powershell
python -X utf8 -m index_futures_basis.wind_diagnostics
```
