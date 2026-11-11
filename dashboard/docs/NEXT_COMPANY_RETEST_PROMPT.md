# 下一对话：连续盘中HTTP昨收与DDB双路径复测

2026-11-11，本轮基线596839d，最终发布看Git。先完整读本页、根/dashboard AGENTS、PROJECT_HANDOFF、APP_COMPANY_TEST、APP_VALIDATION、APP_MARKET_OVERVIEW、APP_RELEASE、COMPANY_SYNC，并核验统一codex/company-apps及远端/worktree/diff。必要实施、测试和精确推送授权持续。

用户最新要求DDB不暂停，手动似乎已可连，下一轮和HTTP一起测试。用户最新要求DDB不暂停，继续原自动数据VPN/历史补齐；已手动连接且新地址192.168.198.77:8904可达时复用现有隧道，不重复登录。实时VPN仍手动，原DDB/VPN配置、账户密码和原文件不改。

HTTP缺显式交易日时，仅在连续交易时段用两次已归档行情交叉核验：同实际代码/稳定昨收、真实市场字段变化、源时钟随接收时间推进且新鲜；通过后按交易日历补准确前一日close，并明确标注corroborated_live_session/日期推定，不能声称交易所认证日期。盘前/午休/盘后、静止或陈旧快照、冲突日期及换日/换时段证据不放行。 438项独立完整回归通过，103.831秒（含加载），无跳过、ResourceWarning作为错误；原420项重跑，新增18项连续会话证据、日期边界、缓存重算与DDB隧道复用验证。

## 新反馈该查什么

先核验HEAD/9JSON等完整性/同次开窗关闭，关注data_gaps.http_previous_close.session_inferred_rows、date_evidence、rejected、cached_closes.source_date_basis；窗口http_session_inferred_count/dates和真实缺价日期。无日期时必须连续盘中两份市场/源时推进且昨收稳定的raw证据，推定不冒称源日期认证。午休/盘前盘后不放行；更早缺口仍给DDB。

看DDB有效端点192.168.198.77:8904、maintenance目标/stage/updated_at/error_code，app_reports.history_update.ddb_vpn.mode/tcp_verified。用户已手动连接且可达应existing_tunnel，不重复登录；不自动切实时VPN，不登出DDB VPN。普通HTTP重试不重连DDB。复测脚本保持原入口、15分钟及安全JSON包，按钮“一键补齐收盘”，默认Overview离线。

## 已知公司证据

596839d包20261111_130843_453_safe_132818_292_0006d0f5.zip：9JSON完整/关闭6.494秒，HTTP20标的source_trade_date_missing、0补入，DDB route/waiting_vpn/login（汇总代码），11-10四指数+16期货缺价，16当前年化有值/20与60全空。原30937eb包午休有值实际是11-09参考；不能当11-10已补齐。新方案待新包，不用本机有界HTTP直连超时当公司源失败。

## 保护

本轮冻结8455文件/365780841字节，全部大小/SHA不变；一份前序下载ZIP在本轮编辑前已不存在，记录preexisting_absent.json。APP_RELEASE.backtest原对象及原序列化块、四受保护提示词和七份唯一SHA归档保留。 其它模块/worktree、原配置/凭据/Excel/行情/分红/依赖不动。逐日D、简单年化、连续00–03的20/60/排当日/T<5/等值半权保持，历史缺D暂0仅派生、当前D不补0、32/A02暂停。不强杀/删锁/重映射Y，不reset/clean/全量stage/强推。原Y盘源/B1口径继续。
