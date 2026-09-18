# 本地数据下载界面

此目录保留早期网页入口。当前主入口为 [CustomTkinter 桌面应用](../desktop/README.md)，Windows 可双击 `index_strategy/start_app.cmd`。两个界面复用 `instant_dld/service.py` 和本地配置，但各自运行任务，不要同时启动同一采集。

页面导航包含「数据下载 → 交易数据下载 / 实时下载」。实时下载已经接入现有采集模块；交易数据下载入口暂作预留。

## 启动

在仓库根目录、激活 `swhy_delta1` 后：

```powershell
python -m index_strategy.frontend --open
```

浏览器地址为 `http://127.0.0.1:8766`。普通 PowerShell 也可直接使用统一目录里的环境：

```powershell
cd P:\project\swhy\Delta1\project
& 'P:\code_content\python_work_env\conda_env\swhy_delta1\python.exe' -s -m index_strategy.frontend --open
```

`--open` 自动打开浏览器，可省略。端口被占用时指定 `--port 8767` 等其他空闲端口。网页服务仅监听本机，不部署到公网。无需 Node/npm、构建步骤或额外 Python 运行依赖。

## 使用

1. 在实时下载页修改标的列表：支持每行一个、逗号分隔、JSON/Python 字面量 list，也可导入多个 `.json`、`.txt`、`.list` 文件。导入会用合并去重后的结果替换编辑框。
2. 设置每轮采集间隔（秒，可以是正数小数），填写本机数据文件夹路径。相对路径以仓库根目录解析；不存在的目录在启动采集时创建。
3. 点击「保存配置」仅保存设置；点击「开始采集」会先保存设置再启动后台任务。
4. 页面显示采集状态、轮次、已保存批次数、最近请求耗时，以及每秒刷新的运行日志。批次数不是标的行情条数；异常批次的失败标的和错误说明写入实时库。
5. 点击「停止采集」后，等待当前请求完成或超时、落盘，再转为「已停止」。运行期间锁定参数，停止后可以修改和重新开始。

关闭或刷新网页不会停止采集，重新进入可以继续查看同一个任务。请先点击「停止采集」再结束使用；在启动网页服务的终端按 Ctrl+C，会同时请求停止任务并关闭网页服务。

日志窗口保留最近 600 条，支持自动滚动、复制和清空显示。清空显示不会删除磁盘文件。多次点击开始或多个页面同时启动时，后端只允许一个运行任务；已有命令行采集进程不归这个页面管理。

## 本地设置与落盘

初次打开读取 `index_strategy/instant_dld/config/symbols.json`，默认间隔 5 秒，保存到 `Z:\Project_data\realtime_market`。

页面设置持久化到 `localsetting/realtime_ui.json`，不会修改 Git 中的默认标的文件。每个实例使用独立的 `localsetting/realtime_symbols_<实例编号>.json` 供采集器使用。本机配置均由 `.gitignore` 排除。保存设置时不要求连接公司 VPN；实际采集仍需要访问公司的行情接口。

保存格式沿用已有模块：

```text
数据目录/
├── data/标的/YYYY/MM/日期.哈希.parquet  # 完整发布的增量行情分片
├── live/quotes.sqlite3                # 实时行情、批次结果、运行摘要、事件
└── strategy_results/策略名/            # 独立策略计算结果
```

每个标的一次有效采样为一行，保留最新价、累计/区间成交量、五档盘口与秒级时间。每批先实时事务入库；首批、每分钟及停止时发布不可变 Parquet。策略直接读取实时库，无需等待归档；详见 [采集模块说明](../instant_dld/README.md)。

## 结构与测试

- `service.py`：兼容导入，服务实现位于 `instant_dld/service.py`。
- `server.py`：仅本机访问的 HTTP API 和静态文件服务。
- `static/`：原生 HTML/CSS/JavaScript，无 CDN 依赖。
- `tests/test_frontend.py`：配置恢复、非法配置、请求完成后停止、重复启动、错误反馈、HTTP 接口及导入测试。

在仓库根目录运行 `python -m unittest discover -s tests -v`。测试使用临时目录和模拟行情，不访问公司接口。
