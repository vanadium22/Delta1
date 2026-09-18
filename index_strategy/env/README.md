# 环境建立与恢复

标准环境名是 `swhy_delta1`。本机所有 Conda 环境统一放在 `P:\code_content\python_work_env\conda_env`。实时采集采用 Python 3.13 和 `requests`，桌面窗口采用 CustomTkinter 6.0.0 / Tk，Parquet 保存和策略 DataFrame 接口使用 pyarrow / pandas；事务库使用 Python 自带的 sqlite3。Python 包版本在 `environment.yml` 与 `requirements.txt` 中固定，Conda 环境文件还包含 Tk 运行库。

## 第一次建立

在仓库根目录、Conda 已初始化的终端中执行：

```powershell
conda env create --prefix P:\code_content\python_work_env\conda_env\swhy_delta1 --file index_strategy/env/environment.yml
conda activate P:\code_content\python_work_env\conda_env\swhy_delta1
python -m pip check
python -m unittest discover -s tests -v
```

已有 `envs_dirs` 指向上述统一目录时，也可使用 `conda env create -f index_strategy/env/environment.yml` 和 `conda activate swhy_delta1`。

在本机普通 PowerShell 中，如果找不到 `conda`，可以用完整路径调用管理器：

```powershell
& 'P:\code_content\anaconda\install\Scripts\conda.exe' env create --prefix 'P:\code_content\python_work_env\conda_env\swhy_delta1' --file 'index_strategy/env/environment.yml'
```

也可以直接用已创建的解释器运行程序：

```powershell
& 'P:\code_content\python_work_env\conda_env\swhy_delta1\python.exe' -s -m index_strategy.instant_dld --interval 5
& 'P:\code_content\python_work_env\conda_env\swhy_delta1\python.exe' -s -m index_strategy.desktop
```

`environment.yml` 配置了 `PYTHONNOUSERSITE=1`，激活后不会混用用户目录的其他 Python 包。直接调用解释器时加 `-s` 可达到同样效果。VS Code 本机选择这个解释器即可，`.vscode` 配置不提交。

## 更新与其他系统

环境已存在时，不要重复创建；使用以下命令安装仓库固定的依赖：

```powershell
conda activate swhy_delta1
python -m pip install -r index_strategy/env/requirements.txt
python -m pip check
```

本机已有 Tk，更新 pip 依赖即可运行桌面窗口。若其他机器缺少 `tkinter`，用 `conda install -n swhy_delta1 -c conda-forge tk` 补齐。只使用系统 Python 的 Linux 机器需通过系统包管理器安装匹配版本的 Tk。

环境文件使用 `conda-forge`，不包含绝对路径，其他系统可使用 `conda env create -f index_strategy/env/environment.yml`。Python 固定到 3.13 系列，Conda 运行库和补丁版本由求解器选取；这不是逐字节相同的系统镜像。当前本机验证版本为 Python 3.13.15。

## Wind 可选依赖

实时采集已包含 pandas、pyarrow，不需要 Oracle。需要历史数据模块时，在同一环境中执行：

```powershell
python -m pip install -r index_strategy/data_dld/requirements_wind.txt
```

Oracle Instant Client 是需要另行配置的本地原生客户端，不属于 pip/Conda 环境文件。可用 `ORACLE_CLIENT_LIB_DIR` 指定本机客户端目录；旧机器已有的 `.runtime` 和 `.deps` 仅作兼容回退，不进入 Git。
