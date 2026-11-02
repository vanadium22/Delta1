# 公司回测与策略框架验证

用户已授权公司电脑的必要测试；以下入口使用明确配置，不要求再次申请测试许可。开发机通过不能代替公司实际运行，结果分别记录。统一分支 `codex/company-apps`，在原公司 Git 根正常 `git pull --ff-only` 后重开回测。

## 离线检查

复用公司既有 Python 和看板依赖，不重装 Wind、不启用 DDB/VPN、不打开 Excel。进入 `git rev-parse --show-toplevel` 对应的仓库根，使用已核验的 Python（公司原环境示例 `D:/conda/envs/swhy_delta1/python.exe`）：

```powershell
& 'D:/conda/envs/swhy_delta1/python.exe' -B -W error::ResourceWarning -m unittest discover -s dashboard/backtest/test
& 'D:/conda/envs/swhy_delta1/python.exe' -B -m dashboard.backtest.test.validate_strategy_ui --output 'local_artifacts/validation/company-backtest-新日期时间'
```

第二条必须指定不存在的新目录；全部输入为隔离合成夹具，离屏验证桌面生成目标→回测、d0=0、实际合约成交及 1080p/4K，不依赖真实数据或 Z 盘。保留本机 `validation.local.json`、本轮 HEAD、退出码和截图。不要将合成结果当策略证据。

## 公司真实输入

通过 `dashboard/start_backtest.vbs` 打开独立窗口：

1. 指定公司 Delta1/data 行情、实际合约参考、历史保证金率或明确固定假设。T 来自挂牌/到期参考或 `days_to_expiry_path`；默认 d0=0。公司原配置与凭据保留，不使用 Z 盘。
2. 在“因子与CTA”选择品种/档位、年化或分位、窗口、固定/Z 阈值、方向与每档占用。分红使用已有逐日版本库，或明确的点数/调整价输入。
3. 生成后核对有效因子数量、缺项提示、实际合约目标路径。没有完整历史 D 时分位应缺失，不能改成零或缩短窗口冒充完整。
4. “检查数据”后回测，分别核对日频/自动模式、末条信号顺延、分钟缺失的真实日线回退，以及 T<=d0 当日 close 的 `expiry_d0` 成交、手数、费用和其他合约仍保留。
5. 复制实际成交表位置；重新打开同一运行目录核对结果。关闭时等待本轮后台任务安全结束，不强杀进程或删除锁。

命令行也可使用 `dashboard/backtest/run.py run --config <本机配置> --d0 0 --precision 1d --workers 2 --output <新的本机目录>`；策略生成入口见 [strategy/README](strategy/README.md)。

记录实际 HEAD、Python 位置、所用配置位置、输入区间、有效因子/缺项数量、真实成交检查及关闭结果。真实行情、分红、指令、数据库、原始异常、凭据及完整真实结果保持公司本机，不随源码提交。后续 DDB 自动更新另行制作，正式数据落 Delta1/data，按既有连接和安全退出流程接入。
