# 下一对话：期限结构、同事配置与后续打包

2026-11-12期限结构与同事配置续改，统一codex/company-apps，实施基线da2aca5，运行版本以Git HEAD/远端为准。概览及股指期货页年化曲线共用每档回退：当前有效优先，缺项沿用同实际合约、同到期日的完整F/S/D/T，空心点及“沿用”、混合时点和原源时可见；每个期现仍须3秒配对，换档/到期修订及T<5不错误沿用。无真实历史值不伪造。

537项完整回归通过，135.572秒（含加载），无跳过，ResourceWarning作为错误。 本地PySide6主窗口使用合成数据做125%/1536×864及860×620离屏检查；上证50两档模拟暂缺时仍显示4点和沿用标记。离屏合成结果不等于公司实际行情或公司验收。

## 可复制提示词

请继续Delta1公司看板。完整读取本文件和docs/INDICATOR_PAGE_PROPOSAL.md，再读取相关AGENTS、PROJECT_HANDOFF、APP_COMPANY_TEST、APP_VALIDATION、APP_MARKET_OVERVIEW、APP_RELEASE、PORTABLE_SETUP和COMPANY_SYNC。统一工作区P:/project/swhy/Delta1/company-apps-worktree、codex/company-apps；先核验Git、远端、worktree、status和diff。

核验我提供的最新公司安全反馈，同次开窗与关闭按report_path匹配；检查上证50两处期限结构的当前/沿用点、真实源时、换合约及T<5，不把缓存说成实时；检查新UNC直连及DDB现有隧道，保留本机账号和原数据。按用户后续指示决定何时准备分发包，未获最新开始指示不制作ZIP；本地验证与公司验收分开。

新用户可在数据更新/设置填写DDB和数据VPN账号；VPN需核验HTTPS网关及证书SHA256指纹。用户名和密码按当前Windows用户DPAPI保存在新版本本机文件，旧文件保留，界面不回显密码；保存凭据不主动暂停DDB。首次配置默认使用本看板本地账户文件，不自动发现其他应用账户；可达时继续复用已有数据隧道，实时VPN仍手动。

常用入口的Python环境设置或看板设置可选择解释器、检查要求的包和版本，并将完整依赖安装到看板专用隔离目录；优先使用随包wheelhouse，否则用户点击时使用pip配置源。校验成功才切换隔离目录，原Python包不修改；不同Wind/历史解释器不继承不兼容的本看板二进制依赖。启动器支持runtime/python/python.exe，且支持选择外部Python；Wind终端和VPN客户端仍须本机具备。

公盘默认 `\\192.168.91.230\FTPServer\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026`，由公司安全包已记录的Y映射根推导；直接UNC访问尚待公司验证。旧内置Y和旧UNC仅运行时转换，用户自定义和显式空白不变；新安全反馈记录share_source.json，旧drive_y.json仍可兼容读取，不强制映射盘符。

用户暂不打包：本轮未制作或发送分发ZIP，也未制作完成可搬运Python运行时或完整离线wheelhouse。后续打包需准备适用于同事机器的独立Python和依赖、经允许的数据与概览缓存，使用白名单并排除个人配置、凭据、Git历史、运行日志及备份；在干净Windows目录解压、断网启动并验证后，才可称解压即用。现有数据包按根目录定位，迁移后仅重定位其自身历史路径和看板生成的本地账户引用，不覆盖用户自定义路径。

原数据、配置、凭据、Excel、其他worktree、四份受保护提示词及APP_RELEASE.backtest原块保留；逐日D、简单年化、连续四档固定20/60保持，历史缺D暂0只派生、当前D不补0、冲突不填；32项/A02继续暂停。Overview默认离线，DDB不暂停，实时VPN手动；不强杀写入者、删锁、重映射Y、reset/clean、全量stage或强推。

## 最新公司证据

上次公司包20261112_111531_749_safe_113124_158_68fd3bf7.zip运行a628472，同次关闭7.247秒、DDB复用隧道并认证、三个指标绘图间隔约30秒；跨午休定价模式不能证明连续盘中tick。本轮新版本尚无公司安全包或直接UNC连接证据。
