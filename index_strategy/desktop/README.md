# Delta1 桌面应用

使用 CustomTkinter / Tk 构建独立桌面窗口。桌面入口直接调用 Python 采集服务，无需浏览器、HTTP 服务或前端构建步骤。

## 启动

Windows 双击上一级的 `index_strategy/start_app.cmd`。启动器使用本机统一环境目录中的 `P:\code_content\python_work_env\conda_env\swhy_delta1\pythonw.exe`，不会自动开始采集。

也可在仓库根目录运行：

```powershell
conda activate swhy_delta1
python -s -m index_strategy.desktop
```

新电脑先按照 [环境说明](../env/README.md) 建立环境。环境位置不同，可设置 `SWHY_DELTA1_PYTHON` 为该环境中 `pythonw.exe` 的完整路径；或激活自己的环境后使用上述模块命令。Windows 启动器失败时显示说明；Python 启动错误会弹窗，并记录到 Git 忽略的 `localsetting/desktop_error.log`。

## 使用

1. 在左侧选择「数据下载 → 实时下载」。交易数据下载目前为预留页面。
2. 修改标的列表：每行一个代码，也支持 JSON / Python 字面量 list。可用系统文件窗口多选导入 `.json`、`.txt`、`.list`，与编辑区合并、统一大写并去重；也可导出 JSON list。
3. 填写采集间隔，单位为秒，支持 `0.5` 等正小数。选择数据保存文件夹，也可直接填写路径；相对路径按仓库根目录解析。
4. 「保存配置」供下次打开恢复；「开始采集」会先校验并保存配置，再启动后台采集。需要公司内网或 VPN。
5. 在右侧查看实时日志、成功/异常批次数、最近响应时间；上方显示采集轮数、已保存批次及耗时。日志窗口保留最近约 800 行；清空窗口不会删除磁盘数据。可以关闭自动滚动查阅旧日志。
6. 点击「停止采集」后，等待当前请求完成或超时并保存，再恢复编辑和启动按钮。采集期间配置锁定，修改后需重新开始。关窗也会先停止并保存，界面继续响应，完成后自动退出。

导入是读取文件当时的内容，不持续关联源文件。桌面配置保存在 `localsetting/realtime_ui.json`，每次启动写入 `localsetting/realtime_symbols.json` 作为采集文件。与早期网页界面的已保存配置兼容；不要同时在两个入口启动同一任务。程序启动后不会自动恢复未结束的任务。

## 数据格式

格式仍为 **JSONL**，按日期和运行编号追加保存，一行对应一个请求批次，包含完整行情响应、请求标的、采集时间和状态。不是每个标的一行，也不是 CSV / Excel。

默认目录：`index_strategy/instant_dld/data`。每次开始都有独立运行编号，不覆盖以前的数据；「打开数据文件夹」可在资源管理器查看。细节见 [实时采集说明](../instant_dld/README.md)。

配置、数据、错误日志均被 Git 忽略。窗口关闭流程会等待正常收尾；强制结束 Python 进程或断电无法保证最后一条记录完整。

## 验证

```powershell
python -s -m unittest discover -s tests -v
```

桌面测试使用真实 GUI 控件、临时目录与模拟请求，覆盖配置恢复、多文件导入、目录选择、开始/停止、关窗等待、后台异常及导航。需要可用的 Tk 显示环境；无显示服务器的 Linux CI 可使用 xvfb，缺少 GUI 环境时桌面测试会明确跳过。
