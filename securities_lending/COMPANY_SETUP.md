# 公司环境配置：swhy_delta1

本机现有环境为 `swhy_delta1`，Python 3.13.15（64 位）。本次已为该环境补齐 PySide6-Essentials 6.11.2、openpyxl 3.1.5、xlrd 2.0.1，未安装 WindPy。公司建议环境路径为 `D:\conda\envs\swhy_delta1`。

## 首次建立环境

同步 `codex/securities-lending` 分支后，在 **Conda 已初始化的终端**中进入 Delta1 仓库根目录：

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

双击 `securities_lending/start.cmd`。App 使用原生 Qt 窗口，正常 Windows 启动使用 `pythonw.exe`，Wind 子进程使用同目录 `python.exe`。界面底部以及设置对话框会显示实际使用的解释器，便于核对。

解释器选择顺序：

1. `D1_LENDING_PYTHON` 环境变量。
2. 项目通用 `SWHY_DELTA1_PYTHON` 环境变量。
3. 本机 `securities_lending/python.local.txt` 中的一行完整解释器路径（Git 忽略）。
4. 公司默认 `D:\conda\envs\swhy_delta1\python.exe`。
5. 当前激活或 Conda 注册表中的 `swhy_delta1`。

如果公司使用了其他环境名/位置，可设置 `SWHY_DELTA1_PYTHON`，或新建上述 `python.local.txt`。不要把本机配置提交到 Git。Wind Python 路径留空时使用 App 同一环境，不会自动改用系统 Python。

首次在 App 填写共享盘中的「发送券单」目录并保存，后续每次启动自动读取当日目录。若只想验证界面，双击 `start_demo.cmd`，演示会明确标识合成库存与合成价格。

## 股数示例

目标名本 `500 万元`、Wind 返回价格 `1400.25 元` 时，需求为 `3500 股`，取整名本 `4,900,875 元`，剩余 `99,125 元`。若库存只有 `3299 股`，最大可借按 100 股取整为 `3200 股`，显示库存不足，不把需求悄悄改成可借上限。

价格和数量都会显示来源/时间，实际券单表头、费率口径、Wind 行业字段与权限仍需公司联调。
