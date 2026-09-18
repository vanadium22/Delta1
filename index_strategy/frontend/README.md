# 本地数据下载界面

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
4. 页面显示采集状态、轮次、已保存批次数、最近请求耗时，以及每秒刷新的运行日志。批次数不是标的行情条数；异常批次也会保留原始响应或错误证据。
5. 点击「停止采集」后，等待当前请求完成或超时、落盘，再转为「已停止」。运行期间锁定参数，停止后可以修改和重新开始。

关闭或刷新网页不会停止采集，重新进入可以继续查看同一个任务。请先点击「停止采集」再结束使用；在启动网页服务的终端按 Ctrl+C，会同时请求停止任务并关闭网页服务。

日志窗口保留最近 600 条，支持自动滚动、复制和清空显示。清空显示不会删除磁盘文件。多次点击开始或多个页面同时启动时，后端只允许一个运行任务；已有命令行采集进程不归这个页面管理。

## 本地设置与落盘

初次打开读取 `index_strategy/instant_dld/config/symbols.json`，默认间隔 5 秒，保存到 `index_strategy/instant_dld/data`。

页面设置持久化到 `localsetting/realtime_ui.json`，不会修改 Git 中的默认标的文件。每次开始时导出 `localsetting/realtime_symbols.json` 供现有采集器使用。这两个文件和本机路径均由 `.gitignore` 排除。保存设置时不要求连接公司 VPN；实际采集仍需要访问公司的行情接口。

保存格式沿用已有模块：

```text
数据目录/
├── YYYY-MM-DD/运行编号/batches.jsonl    # 每个请求一行，完整 JSON 响应/错误
└── runs/运行编号/
    ├── run.json                        # 参数和最终运行摘要
    └── events.jsonl                    # 运行事件
```

JSONL 是每行一个独立 JSON 对象，不是 CSV/Excel，也不是逐笔行情流。每次启动采用独立运行编号，不覆盖旧数据。底层请求保持直连内网和 TLS 证书校验；超时、业务失败、缺失标的及磁盘错误的行为见 [采集模块说明](../instant_dld/README.md)。

## 结构与测试

- `service.py`：独立采集线程、配置校验与持久化、开始/停止、统计和日志。
- `server.py`：仅本机访问的 HTTP API 和静态文件服务。
- `static/`：原生 HTML/CSS/JavaScript，无 CDN 依赖。
- `tests/test_frontend.py`：配置恢复、非法配置、请求完成后停止、重复启动、错误反馈、HTTP 接口及导入测试。

在仓库根目录运行 `python -m unittest discover -s tests -v`。测试使用临时目录和模拟行情，不访问公司接口。
