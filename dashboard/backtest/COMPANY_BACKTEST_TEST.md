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

## 60 日反向持有到期专项

先按 [CARRY_STUDY](CARRY_STUDY.md) 准备 `carry.config.example.json` 的本机副本。四个指数、逐日四档实际期货、挂牌/到期参考及前 60 个交易日暖启动必须完整；普通窗口不会补数据。已知混合 Z 来源缓存即使位于其他盘也会拒绝；不能改标签绕过。当前开发机的纯来源覆盖不能替代公司完整历史。

公司已有 DDB 数据路由可用时，可使用原 SDK 解释器显式运行 `python -m dashboard.backtest.acquire_daily --connection <原连接文件> --output <新data目录> --start 2023-07-01 --end 2026-11-02`。该命令只读有界查询并生成 SHA/覆盖/本机配置，不连接或登出 VPN。真实网络连接动作须遵守当前用户授权与审批；自动审批已拒绝的动作不能改客户端重试绕过。

严格专项入口 `python -m dashboard.backtest.carry_study --config <本机study配置> --output <新的输出目录>`。默认日频、D=0、60 日、0.9/0.8 反向绝对值择优且持有到期，另跑所有实际合约独立对冲账户。10m 资金、固定 15% 保证金和每腿每边万三须核对情景；完整区间不足时应失败留审计，不把 `--allow-partial` 结果标成完整。

逐笔检查 IF/IH 期货手数×300、IC/IM×200 等于反向指数单位；中间不调手数、到期两腿同 close 平仓、下一组信号严格顺延。`trades`、两腿归因总和及总权益应对账。双击原桌面入口重开四个阈值/分组目录，检查实际合约、指令页、关联标记、费用和回撤。可离屏复验：

```text
python -B -m dashboard.backtest.test.validate_carry_ui --study <本机study结果目录> --output <新的本机验证目录>
```

本命令仅重开明确选择的本机结果，在 1080p/4K 检查账户、规则、各明细页及截图，不启动 VPN、不下单。真实截图和检查记录保持公司本机。
