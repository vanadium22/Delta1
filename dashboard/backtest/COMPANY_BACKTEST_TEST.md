# 公司回测与策略框架验证

用户已授权公司电脑的必要测试；以下入口使用明确配置，不要求再次申请测试许可。开发机通过不能代替公司实际运行，结果分别记录。统一分支 `codex/company-apps`，在原公司 Git 根正常 `git pull --ff-only` 后重开回测。

## 当前相邻跨期专项：公司调用（2026-11-04）

当前模板为01-02/02-03 × 四品种，仅原始q_open=.9、持有到期，共8个独立账户。用户最新要求双腿保证金各100%；执行重新算整数手数、完整名义每腿每边万三费用及权益。收益数值与分布合并，标明累计/每笔非年化收益和年化CAGR；后置收益/回撤曲线。亏损详图明确买卖方向，上半实际点差、下半带方向含费净盈亏点数。先交PNG/HTML示例，用户确认后才做新版PDF；旧20%及48方案/PDF保留。

复制当前无数据模板到本机配置目录，设置已有审计快照的位置和真实来源声明，运行：

```powershell
python -m dashboard.backtest.calendar_study --config dashboard/localsetting/backtest/calendar_reversal.local.json --output outputs/backtest/calendar_adjacent_margin100_company01 --q-open 0.9 --exits expiry --no-render
```

factor.parameters.channels必须为["01-02","02-03"]。不可把旧01-03因子的CTA标签改成01-02；改变channels或window_days必须重算，之后阈值/退出/品种可复用该保存因子。此命令完整验证8个单独重跑、因子重读、3个前缀和逐笔对账，--no-render仅跳过旧48方案报告生成器，不连接Z/DDB/VPN。标准factor/cta/run和两通道tune命令见 [CALENDAR_REVERSAL](CALENDAR_REVERSAL.md)。公司现场有效参数、覆盖末日及8/8对账需另行记录，不能以本机通过替代。

确认data.margin_rates的IF/IH/IC/IM均为1.0且margin_rate_path为空；从20%切到100%可复用同channels/window的factor_input，因子声明排除执行保证金参数，但必须重跑执行，不能把旧手数收益直接缩放后当新结果。前版48研究的旧报告生成器仍限定原48矩阵及20%保证金，复现时另用0.2本机配置。

## 前版48方案跨期专项（2026-11-03，保留）

使用统一分支 `codex/company-apps` 和公司现有Git根。本次六页跨期专项说明、无数据配置模板及全部可复制命令见 [CALENDAR_REVERSAL](CALENDAR_REVERSAL.md)。这组原始q_open=.8/.9对应p>.8/.9和p<.2/.1，与前轮中心化阈值不同；保证金明确为双腿各20%。此前期现研究和42页PDF保持原位，本次跨期总结单独限6页。

公司只需复用已审计的本地快照（已有公司转移包包含同SHA快照），无需访问Z、DDB或VPN。复现旧48组时在独立本机配置中将factor.parameters.channels改回["01-03","02-03"]，保留原默认完整矩阵；按说明设置data_root、真实来源/version及授权清单，运行时核验SHA。每次指定新输出目录：

```powershell
python -m dashboard.backtest.calendar_study --config dashboard/localsetting/backtest/calendar_reversal_legacy.local.json --output outputs/backtest/calendar_reversal_company01
```

默认48方案并验证48个单独重跑；HTML/PNG/CSV在该输出目录，原生回测文件在cases下，可由既有桌面重开。首次计算一次新跨期因子；之后只改CTA用原factors，改变window_days必须重算。PDF由 `python -m dashboard.backtest.calendar_pdf outputs/backtest/calendar_reversal_company01` 从保存结果生成；依赖reportlab/Pillow/pypdf与Windows微软雅黑。公司缺报告依赖时仍可先查看离线HTML/PNG和CSV，不影响原回测执行。现场有效参数、覆盖末日、48/48及对账结果需单独回传，不能用开发机通过代替公司验收。

## 前轮期现研究：公司获取数据并调参

2026-11-03的仅多期货/空指数研究见 [固定组说明](FIXED_SLOT_STUDY.md) 和 [调参说明](PARAMETER_TUNING.md)。**Git pull只获取源码、说明和无真实数据模板，不包含行情、因子、PDF或真实回测结果。** 本轮PDF及离线数据传输ZIP通过聊天文件交付，留在本机，不提交Git。

推荐下载本轮 `Delta1_company_research_20261103.zip`，解压到公司仓库的 `local_artifacts/company_kit_20261103`。包中有7份已审计快照文件、PDF、离线HTML/图片/CSV、配置模板、`prepare_company.py` 和逐文件SHA；不含凭据或整套72账户执行目录。它使用已获授权的本地快照，准备和回测不访问Z/DDB/VPN。

在公司现有仓库根运行，Python复用原环境，ZIP实际下载路径自行替换：

```powershell
Set-Location 'D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard'
$repo = (git rev-parse --show-toplevel).Trim()
$py = 'D:/conda/envs/swhy_delta1/python.exe'
git branch --show-current
git pull --ff-only
$kit = Join-Path $repo 'local_artifacts/company_kit_20261103'
Expand-Archive -LiteralPath 'C:/YOUR_DOWNLOAD/Delta1_company_research_20261103.zip' -DestinationPath $kit
& $py "$kit/prepare_company.py" --repo $repo
$cfg = 'dashboard/localsetting/backtest/company_20261103'
& $py -m dashboard.backtest.slot_study --config "$cfg/study.local.json" `
  --output 'outputs/backtest/company_long_future_base_20261103'
```

确认分支为codex/company-apps；保留已有改动，不强切/覆盖。脚本校验包SHA及导入清单，写仓库内data快照和新的本机配置；已有完全相同快照只读复用，不同则报错而不覆盖。配置及输出目录必须新建。脚本自身不计算因子或执行回测，可用 `--config-dir` / `--study-output` 指定仓库内新位置。

快照覆盖2023-07-03—2026-10-14，795交易日、172实际合约参考。2023暖启动后从2024-01-02评估；不是截至今天。原Z现货仅到2026-07-08，既有纯行情补到10-14；原始成交价不跨日填充。data中保留allow_readonly_z_import=true及source_manifest_path，读入核验全部使用文件SHA。

跨机器后，旧因子的数据声明仍绑定开发机绝对路径。公司首次study的factor_input为空，按同一快照计算一次；之后公司自己的factors目录用于重复CTA，不能仅改旧因子标签或数据路径来绕过声明校验。首次18case/72账户输出在上面的新目录，report.html为离线报告，factors/为合并原始因子。

准备脚本生成四份配置：

| 配置文件 | 用途 | 默认规模/复用 |
|---|---|---|
| study.local.json | 首次固定组完整比较 | 18case/72账户；三类原始因子一次生成 |
| cta_tuning.local.json | 两方法×四档×阈值.9/.8 | 16配置/64账户；复用首次factors，因子计算0次 |
| factor_tuning.local.json | 窗口40/60及两方法/档位/阈值 | 32配置；factor_input=null，按函数/窗口分别计算 |
| calendar_tuning.local.json | 01—03跨期窗口40/60×阈值 | 4配置；跨期仍为双向反转 |

```powershell
& $py -m dashboard.backtest.workflow tune --config "$cfg/cta_tuning.local.json" --plan
& $py -m dashboard.backtest.workflow tune --config "$cfg/cta_tuning.local.json" `
  --output 'outputs/backtest/company_cta_tuning_20261103'
& $py -m dashboard.backtest.workflow tune --config "$cfg/factor_tuning.local.json" `
  --output 'outputs/backtest/company_factor_tuning_20261103'
& $py -m dashboard.backtest.workflow tune --config "$cfg/calendar_tuning.local.json" `
  --output 'outputs/backtest/company_calendar_tuning_20261103'
```

批次候选值在tuning.grid里修改，grid覆盖基础参数。window_days/回归模型属于factor；threshold、direction、allowed_future_side、position_weight和候选slots属于CTA；费用/资金属于backtest。只多期货空指数保持allowed_future_side="long"及direction=-1；.9/.8分别仅p<.05/.10入场并持有到期。若改变首轮输出位置，同步cta_tuning.factor_input。输出每次新命名，别覆盖旧实验。

桌面单次仍双击dashboard/start_backtest.vbs，在四页配置中修改；相同因子用“仅运行CTA”，窗口/模型改变先重算。批次从workflow tune运行，保存每组summary及variants/vXXXX/job.local.json和原生backtest，可由桌面重开。

本机已验证包内SHA、795日/172合约读入及1/16/32/4组配置计划，原40个输入/因子SHA不变。公司现场仍需实际运行；不把开发机验证当公司验收。若公司已有标准或注册行情，可直接按DATA_FORMAT配置；如需从Z重建，独立readonly_import只读导入新快照，见FIXED_SLOT_STUDY，**DDB获取和VPN继续暂停**。

## 离线检查

复用公司既有 Python 和看板依赖，不重装 Wind、不启用 DDB/VPN、不打开 Excel。进入 `git rev-parse --show-toplevel` 对应的仓库根，使用已核验的 Python（公司原环境示例 `D:/conda/envs/swhy_delta1/python.exe`）：

```powershell
& 'D:/conda/envs/swhy_delta1/python.exe' -B -W error::ResourceWarning -m unittest discover -s dashboard/backtest/test
& 'D:/conda/envs/swhy_delta1/python.exe' -B -m dashboard.backtest.test.validate_strategy_ui --output 'local_artifacts/validation/company-backtest-新日期时间'
& 'D:/conda/envs/swhy_delta1/python.exe' -B -m dashboard.backtest.test.validate_stages_ui --output 'local_artifacts/validation/company-stages-新日期时间'
```

第二条必须指定不存在的新目录；全部输入为隔离合成夹具，离屏验证桌面生成目标→回测、d0=0、实际合约成交及 1080p/4K，不依赖真实数据或 Z 盘。保留本机 `validation.local.json`、本轮 HEAD、退出码和截图。不要将合成结果当策略证据。

## 公司真实输入

通过 `dashboard/start_backtest.vbs` 打开独立窗口：

1. 指定公司 Delta1/data 行情、实际合约参考、历史保证金率或明确固定假设。T 来自挂牌/到期参考或 `days_to_expiry_path`；默认 d0=0。公司原配置与凭据保留；运行时不直接读Z，用户授权的Z数据仅经独立只读导入并审计后使用。
2. 在“数据配置”核对版本及绝对路径、覆盖、固定 100% 或历史保证金假设、分红 required/ignore；在“因子参数”计算并保存原始因子。
3. 在“CTA 参数”读取同一因子，分别生成 0.9/0.8，核对原始 p 不变；保存配置并重开四页全部设置。在“回测执行参数”核对零和手数权重模式、d0、费用及不变目标保持手数。没有完整 D 且未显式 ignore 时不能补零。
4. “检查数据”后回测，分别核对日频/自动模式、末条信号顺延、分钟缺失的真实日线回退，以及 T<=d0 当日 close 的 `expiry_d0` 成交、手数、费用和其他合约仍保留。
5. 复制实际成交表位置；重新打开同一运行目录核对结果。关闭时等待本轮后台任务安全结束，不强杀进程或删除锁。

命令行也可使用 `dashboard/backtest/run.py run --config <本机配置> --d0 0 --precision 1d --workers 2 --output <新的本机目录>`；策略生成入口见 [strategy/README](strategy/README.md)。

记录实际 HEAD、Python 位置、所用配置位置、输入区间、有效因子/缺项数量、真实成交检查及关闭结果。真实行情、分红、指令、数据库、原始异常、凭据及完整真实结果保持公司本机，不随源码提交。后续 DDB 自动更新另行制作，正式数据落 Delta1/data，按既有连接和安全退出流程接入。

## 60 日反向持有到期专项

先按 [CARRY_STUDY](CARRY_STUDY.md) 准备 `carry.config.example.json` 的本机副本。四个指数、逐日四档实际期货、挂牌/到期参考及前 60 个交易日暖启动必须完整；普通窗口不会补数据。已知混合 Z 来源缓存即使位于其他盘也会拒绝；不能改标签绕过。当前开发机的纯来源覆盖不能替代公司完整历史。

DDB 数据获取继续暂停，当前验证不得调用 acquire_daily 或连接 VPN。旧一次性补取入口保留，等待用户未来新指示。

严格专项兼容入口 `python -m dashboard.backtest.carry_study --config <本机study配置> --output <新的输出目录>`。新默认保证金为 100%；既有 15% 结果保留其显式旧情景，不重写。完整区间不足应失败留审计，不把 `--allow-partial` 标成完整。新研究优先使用 [WORKFLOW](WORKFLOW.md) 的四段配置及独立阶段。

逐笔检查 IF/IH 期货手数×300、IC/IM×200 等于反向指数单位；中间不调手数、到期两腿同 close 平仓、下一组信号严格顺延。`trades`、两腿归因总和及总权益应对账。双击原桌面入口重开四个阈值/分组目录，检查实际合约、指令页、关联标记、费用和回撤。可离屏复验：

```text
python -B -m dashboard.backtest.test.validate_carry_ui --study <本机study结果目录> --output <新的本机验证目录>
```

本命令仅重开明确选择的本机结果，在 1080p/4K 检查账户、规则、各明细页及截图，不启动 VPN、不下单。真实截图和检查记录保持公司本机。
