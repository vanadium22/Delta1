# 数字 Excel 所需历史后台

公司统一分支仅纳入数字 Excel 增量历史维护需要的路由、字段/单位转换、直接查询适配器及本机加密凭据支持。

`catalog.json` 只含股指期货与对应沪市指数的日线/分钟四个来源定义，不含行情、账号或地址。下载沿用旧本地后台的单位和字段口径。这里不是旧 App 的完整历史下载器；不包含其前端、通用任务管理或 VPN 自动化。

连接由 `dashboard.marketdata.history_maintenance.open_direct` 创建，仅使用用户已经连通的网络。`downloader.Client` 不允许直接构造，也不加载 VPN 辅助程序。历史任务获取网络锁，验证新增分片后发布，旧版本保留。

公司入口：`dashboard/start_numeric_excel.cmd`；首次本机 DDB 设置：`dashboard/configure_numeric_history.cmd`。密码经当前 Windows 用户 DPAPI 加密，不随 Git 或数据包传输。只有显式配置命令才保存设置；读取已有凭据不会自动迁移或覆盖。
