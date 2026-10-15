# 公司环境配置：swhy_delta1

家中开发机已验证的环境为 `swhy_delta1`，Python 3.13.15（64 位），包含 PySide6-Essentials 6.11.2、openpyxl 3.1.5、xlrd 2.0.1，未安装 WindPy。公司建议环境路径为 `D:\conda\envs\swhy_delta1`；上述版本记录不代表公司实际环境与 Wind 已验证通过。项目现状和用户反馈见 [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md)。

## 首次建立环境

公司统一使用 `codex/company-apps`，在仓库根目录一次 `git pull --ff-only` 更新全部已发布模块；`codex/securities-lending` 仅用于开发。已有公司环境按下节使用，无需重建。

仅首次建立环境时，同步公司分支后，在 **Conda 已初始化的终端**中进入 Delta1 仓库根目录：

```powershell
conda env create --prefix "D:\conda\envs\swhy_delta1" --file securities_lending/environment.yml
conda activate "D:\conda\envs\swhy_delta1"
python -m pip check
python -X utf8 -m securities_lending.diagnose
python -X utf8 -m securities_lending --demo
```

`environment.yml` 是运行券源 App 的最小环境，不包含 WindPy，也没有本机绝对路径。Python 固定在 3.13 系列，补丁版本由 Conda 求解。如果还需要恢复整个 Delta1 行情采集/指数策略环境，可先使用原来的 `index_strategy/env/environment.yml` 建环境，再安装下面的券源 App 依赖。

## 已经有 swhy 环境

不重复创建环境，也不执行带 `--prune` 的环境更新。激活公司已有环境后添加本 App 依赖：

```powershell
conda activate "D:\conda\envs\swhy_delta1"
python -m pip install -r securities_lending/requirements.txt
python -m pip check
```

`install.cmd` 做的也是向已选择环境安装这些依赖，不再创建项目内 `.venv`。包源不可访问时，使用公司批准的 pip 镜像/离线 wheel 即可。

## 在公司安装 WindPy

由你登录公司 Wind 终端，用终端提供的 Python API 安装/修复工具，将接口注册到 **`D:\conda\envs\swhy_delta1\python.exe` 对应环境**。WindPy 不列入公共 pip/Conda 依赖，家里没有 Wind 不影响 App 演示。

安装后用相同解释器检查：

```powershell
& 'D:\conda\envs\swhy_delta1\python.exe' -s -c "import sys; import WindPy; print(sys.executable); print(WindPy.__file__)"
& 'D:\conda\envs\swhy_delta1\python.exe' -s -X utf8 -m securities_lending.diagnose --wind 000001.SZ
```

`diagnose` 默认只检查环境，不连接 Wind；显式加 `--wind` 才试取指定代码的最新价和行业。也可以双击 `diagnose.cmd` 查看当前 App Python、版本、位数、基础依赖和是否发现 WindPy。

公司具体终端版本对 Python 版本/位数的要求需以终端 API 工具说明为准，尚未在公司验证 Python 3.13 的 WindPy 兼容性。如果该终端需要另一版本的 Python，可以把 WindPy 安装在其支持的独立环境，然后在 App「数据与环境设置 → Wind 与环境 → Wind Python 路径」填该环境的 `python.exe`，App 环境仍保持原样。Wind 工作脚本与主 App 通过 JSON 通信，无需在那个 Wind 环境安装 PySide6。

## 日常启动

双击 `securities_lending/start.cmd`。App 使用原生 Qt 窗口，正常 Windows 启动使用 `pythonw.exe`，Wind 子进程使用同目录 `python.exe`。设置对话框和状态栏悬停提示会显示 App 实际使用的解释器，便于核对。

解释器选择顺序：

1. `D1_LENDING_PYTHON` 环境变量。
2. 项目通用 `SWHY_DELTA1_PYTHON` 环境变量。
3. 本机 `securities_lending/python.local.txt` 中的一行完整解释器路径（Git 忽略）。
4. 公司默认 `D:\conda\envs\swhy_delta1\python.exe`。
5. 当前激活或 Conda 注册表中的 `swhy_delta1`。

如果公司使用了其他环境名/位置，可设置 `SWHY_DELTA1_PYTHON`，或新建上述 `python.local.txt`。不要把本机配置提交到 Git。Wind Python 路径留空时使用 App 同一环境，不会自动改用系统 Python。

首次在 App 填写共享盘中的「发送券单」根目录并保存。启动时优先读取项目内已校验的当日券单，已有可用副本时不访问公盘、不重复下载；没有可用副本时才按北京时间定位 `根目录/YYYY-MM-DD/申万内部券单YYYY-MM-DD.xlsx`，先下载到项目 `securities_lending/data/live` 的日期/批次目录，再读取本地副本的「库存券单」。顶部「打开下载位置」打开实际下载批次，读取失败的文件也可定位；「文件与同步详情」可直接打开本地 Excel。盘中需要获取公盘更新时，点击「同步当日券单」或按 F5 强制下载。

文件名模板（支持 `{date}`）、Sheet 名、表头行、具体列名均可在设置中修改。默认逐笔取「实际可融股数」与「可融股数」的较小值，再按证券汇总；参考费率 0.05 显示 5%。库存市值按有效股数乘本次 Wind 最新价计算，原始券单市值只供追溯。任一必要数量列缺失时不确认上限。

界面适配 1920×1080 屏幕，小窗口/高 DPI 下可以横向滚动；「券源明细」按需展开。Ctrl+B 可粘贴 Excel 代码与目标名本两列，金额单位万元。Tab/Enter 下一行，Ctrl+Enter 刷新计算；复制所选行或导出 Excel/CSV 均保留日期、模式和来源。

演示入口仍为 `start_demo.cmd`，设置独立保存至 `data/demo/config.local.json`，不会覆盖正式配置。旧默认配置会在内存迁移到本版文件名与列口径，启动不会自行写回配置。

## 股数示例

目标名本 `500 万元`、Wind 返回价格 `1400.25 元` 时，需求为 `3500 股`，取整名本 `4,900,875 元`，剩余 `99,125 元`。若库存只有 `3299 股`，最大可借按 100 股取整为 `3200 股`，显示库存不足，不把需求悄悄改成可借上限。

价格和数量都会显示来源/时间，实际券单表头、费率口径、Wind 行业字段与权限仍需公司联调。
