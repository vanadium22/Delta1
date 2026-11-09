# 公司回测与策略框架验证

用户已授权公司电脑的必要测试；以下入口使用明确配置，不要求再次申请测试许可。开发机通过不能代替公司实际运行，结果分别记录。统一分支 `codex/company-apps`，在原公司 Git 根正常 `git pull --ff-only` 后重开回测。

2026-11-09追加同日close开仓对照：默认entry_timing=next_observation不变。仅研究用户授权的新假设时，在本机新配置设backtest.entry_timing=signal_close，study用`--q-open 0.9 --exits close0.5 --sides both --no-render`；普通workflow还须cta.parameters.entry_timing一致。开仓当日close、0.5退出下一有效观测、到期同日双平。公司须核对8账户信号日=开仓日、信号p=成交p、真实close及费用/持仓，并与旧口径分别保存，不能混用日期/分位或覆盖旧结果。完整命令见[跨期说明](CALENDAR_REVERSAL.md)。本机已完成验证，公司现场另行记录。

## 当前相邻跨期专项：双向反转、仅持有到期（2026-11-05）

用户最新删除0.5退出；同一账户允许低尾做多、高尾做空，只持有到期。两通道×四品种分别独立，共8账户。复制无数据模板并填已有审计快照，本机因子可复用时配置factor_input；四品种保证金率均为1.0，费用每腿每边万三。执行：

```powershell
python -m dashboard.backtest.calendar_study --config dashboard/localsetting/backtest/calendar_reversal.local.json --output outputs/backtest/calendar_expiry_company01 --q-open 0.9 --exits expiry --sides both --no-render
```

开仓是p<0.1多近空远、p>0.9空近多远的严格反转，下一有效观测成交；实际pair锁定至任一腿到期当日close双平。方向必须both，命令含8账户独立重跑与逐笔对账。不能把单尾结果相加代替同账户双向策略。当前tune模板固定expiry、两通道2配置/8品种账户。新版PDF从已验证到期结果直接放大排版，不重跑因子/CTA/执行，前版中位退出结果留作归档。详细口径见[跨期说明](CALENDAR_REVERSAL.md)。公司现场覆盖与8账户核验须单独记录。Git只同步说明和无数据模板，真实数据、配置和报告不入Git。

## 前版相邻跨期专项：双向持有到期（2026-11-04）

当前模板为01-02/02-03 × 四品种，仅原始q_open=.9、持有到期，共8个独立账户。用户最新要求双腿保证金各100%；执行重新算整数手数、完整名义每腿每边万三费用及权益。收益数值与分布合并，标明累计/每笔非年化收益和年化CAGR；后置收益/回撤曲线。亏损详图明确买卖方向，上半实际点差、下半带方向含费净盈亏点数。用户已确认全历史示例并要求补分位、更新PDF，6页新版已完成；旧20%及48方案/PDF保留。

最新预览同时提供四品种全历史近减远原始点差，各品种最大单笔持仓回撤的实际pair和持仓/峰谷高亮，以及逐日是否持仓状态带。2026-11-05纠正为整笔开仓至平仓按最终扣费后净PnL着色：盈利整段红、亏损整段绿，未平仓按样本末净浮盈亏；连续参照/空仓灰色。持仓带蓝多价差、紫空价差，2023暖启动单列，平仓当日收盘为空仓。样本末状态注明日期，交互图悬停可查实际代码、方向、每腿手数、trade_id和决定颜色的最终/期末净PnL。公司查图请解压随聊天交付的离线预览包，打开preview.html；本地assets支持交互，无需联网。真实预览、CSV和本机绘图脚本不随Git pull，沿用原100%研究结果，本轮不重新计算账户。

当前6页PDF保留放大图与精简文字，32PNG/30CSV另存；新增trade_segment_colors.csv可逐笔核对曲线颜色及闭合/期末估值基准，原29CSV字节一致。颜色是回看标注，不进入因子/CTA；不能将段内日涨跌或最大回撤段的损益当整笔最终结果。核验与当前文件路径见PROJECT_HANDOFF。

当前大回撤图增加固定实际pair放大和两腿买卖代码/手数文字；专表将整笔与最大回撤段分开，列日期、点差变化、实际pair起止p、原信号p、毛净PnL和区间新增费用。cases内有8份单品种放大及关键节点表。连续档位换合约处断线；跳变表拆成旧pair跨日变化与换pair差异，真实锁定pair价格变化另列。复核时先对专表和实际成交，再看全历史，不能把连续图换档差异当持仓亏损。

新版保留四品种2×2全历史图，各点差下方加入同轴原始p，再下方为实际收盘持仓。灰细线是当日连续通道p，彩色线是锁定实际pair相对入场通道此前60日分布的p，所选案例加粗；只读已保存因子，历史不足留空、排除当日，标0.9/0.1和信号/成交/退出p。首页表前置全部8账户指标，6页A3横向PDF经逐页渲染和原生表逐格CSV对账。完整包含32PNG、30CSV和离线HTML，解压打开preview.html，PDF在output/pdf/。本机核验不替代公司现场运行；原100%账户未重算。

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
