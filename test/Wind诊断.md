# 公司 Wind 诊断：复制命令即可运行

先关闭股指基差 App，并登录公司 Wind 终端。打开 **PowerShell**，按下面两步操作；沿用现有环境，不用重新安装。

## 1. 更新并运行

整段复制到 PowerShell：

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
git pull --ff-only
.\index_futures_basis\diagnose_wind.cmd
```

如果更新报错，先保留完整错误，不要继续运行。诊断通常需要 1—3 分钟；结束后按任意键，回到 PowerShell。

已更新过项目时，也可以直接双击项目里的 `index_futures_basis\diagnose_wind.cmd`。

## 2. 复制结果给我

仍在同一个 PowerShell 窗口，复制运行：

```powershell
Get-Content -LiteralPath '.\data\diagnostics\index_futures_basis\latest.txt' -Raw -Encoding UTF8 | Set-Clipboard
```

然后回到聊天窗口，按 **Ctrl+V** 粘贴整份结果。即使有 `FAIL` 或 `SKIP`，也请复制完整内容。

如果想先查看结果：

```powershell
notepad '.\data\diagnostics\index_futures_basis\latest.txt'
```

以上是默认保存位置；如果设置过自定义数据目录，以诊断窗口打印的实际路径为准，替换命令中的文件路径。如果启动失败、未生成结果文件，直接复制终端里的完整错误。

## 检查了什么

- Wind 连接、近期交易日历、周末及工作日节假日休市；确认零交易日属于正常情况。
- IF / IC / IM / IH 最近已完成交易日的合约映射、到期日、收盘价和持仓量补齐。
- 重复检查是否零新增行情请求，以及只缺一个字段时是否只补该字段。

`PASS` 表示通过；`FAIL` 表示失败；`SKIP` 表示尚未验证。

补齐测试使用独立诊断库，不修改正式行情库。正式行情更新仍在 App 中点击“检查并补齐行情”。无需发送 `probe.sqlite`，只粘贴文本结果即可。

更多说明及指定日期的运行方法见 [完整 Wind 诊断说明](../index_futures_basis/WIND_DIAGNOSTICS.md)；Git 更新和推送命令见 [Git操作指南](../Git操作指南.md)。
