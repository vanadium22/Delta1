# D1 统计工作台

统计是独立的 PySide6 桌面 App，在仓库更新后双击 `statistics_app/start.cmd` 启动。日报查询和人工簿记使用 `script_making/start.cmd`。首次使用沿用原日报模块配置、数据目录及其已生成的统计记录；不会复制或迁移本机数据。

默认读取同一仓库下 `script_making` 目录的配置；需要使用其他已有日报配置目录时运行 `statistics_app/start.cmd --root <原日报模块目录>`。依赖及 Python 选择沿用 `script_making`。若有本地历史日报，打开统计页会沿用原行为自动生成统计；运行 `--startup-check` 只检查窗口，不生成统计。

目前这是独立桌面入口，复用 `script_making` 原有统计实现；原 Work Automation 命令、参数、设置及数据路径不变。查询日报、同步文件仍在日报工作台操作。具体统计口径、邮件及自动化说明见 [日报模块 README](../script_making/README.md)。
