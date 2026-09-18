# Wind 历史数据验证

`wind_connection.py` 提供只读连接和有限行数 SELECT；`wind_smoke_test.py` 检查可见目录并下载日频小样本。`dl_wind_data.py` 是保留的旧研究脚本，依赖尚未随仓库提供的 `utils`，不作为新项目的运行入口。

当前模块是连接与小样本验证工具，尚不是全市场全历史下载器。既往验证日频成功，分钟级入口尚未确认；不会把元数据探测当作分钟数据下载完成。

## 环境与本机配置

先按 `../env/README.md` 建立并激活统一的 `swhy_delta1` 环境，再安装可选依赖：

```powershell
python -m pip install -r index_strategy/data_dld/requirements_wind.txt
```

复制仓库的 `config/examples/wind_db.example.json` 到 `localsetting/wind_db.json`，填写 `user`、`password`、`dsn`。实际配置不进入 Git。也可通过 `WIND_DB_USER`、`WIND_DB_PASSWORD`、`WIND_DB_DSN` 提供，环境变量优先；`WIND_DB_CONFIG` 指定自定义配置文件。

Oracle 11g 等环境需要 Thick 模式时，另行安装 Oracle Instant Client，并设置 `ORACLE_CLIENT_LIB_DIR`。已有机器的 `.runtime/instantclient_*/oci.dll` 自动回退发现；仅在环境未安装 oracledb 时才兼容使用原有 `.deps`。克隆不会携带这些本机依赖或客户端。

## 运行

在仓库根目录运行，`--output` 应是一个尚不存在的新目录：

```powershell
python -m index_strategy.data_dld.wind_smoke_test --output index_strategy/data_dld/data/smoke_example --end-date 20260916 --days 14
python -m index_strategy.data_dld.wind_smoke_test --output index_strategy/data_dld/data/catalog_example --catalog-only
```

不指定 `--output` 时保留原默认值 `Z:\Project\_data\index\_etf\smoke_<时间>`。`--days` 为 1–90 个自然日；省略结束日期时使用数据库会话当前日期的前一天。

完整模式生成目录元数据、样本 Parquet、逐查询结果与 `report.json`，Parquet 保存后读回验证。区间无数据的代码会回退最近 5 条，报告中明确记录 `fallback_to_latest`。实际股指合约月份根据结束日期生成，不代表自动识别主力。

退出码 `0` 表示当前模式完成，`1` 为顶层失败，`2` 为部分完成。完整模式仍因分钟下载未验证而返回 `2`；日频结果需查看报告各组状态。成交量/金额单位、复权、连续期货换月规则保持原始口径，未进行额外假设或换算。
