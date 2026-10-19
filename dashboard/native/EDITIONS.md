# 内部开发与看板发布维护

2026-10-02。此说明仅保存在开发项目，不进入对外交付。

开发工作台包含三个市场页面，以及公式工作台、数据与任务、结果档案。
对外产品统一为 **Delta1 市场看板**；1.0 有「股指期货概览、专题与自定义指标、市场异动」三个页面。
阶段样稿通过同源构建生成，交付范围见 [STAGED_RELEASES.md](STAGED_RELEASES.md)。
公开产品的标题、入口、源码、元数据及 Git 历史均不包含版本关系或管理功能。

## 启动

- `start_developer.cmd`、原 `start_app.cmd`、`start_dashboard.cmd`：六页面开发工作台。
- `start_viewer.cmd`：本机查看三个市场页面，读取 `runtime/published`。
- `start_demo.cmd`：开发工作台合成演示，生成独立 `demo.json`。
- 对方独立 Git 中的 `start_app.cmd`：市场看板；`start_demo.cmd`：合成演示。

两者可并行启动。ETF 数据尚待接入；所有示例明确标为合成。

## 指标与代码更新

| 修改 | 唯一源 | 对外同步方式 |
| --- | --- | --- |
| 三个页面布局、表格、图表 | `market_view.py` | 从当前共享源生成公开 Git，再更新接收方代码 |
| 主题、通用图表 | `theme.py`、`widgets.py` | 同上 |
| 指标与回归计算 | `analytics.py`、`metrics.py`、`model.py` | 开发端统一计算，快照自动更新 |
| 自定义公式 | 工作台的公式页面 | 发布结果与版本自动进入四品种结果矩阵，无需修改通用 UI |
| 新字段 | `publication.py` 白名单与页面 | 更新 SCHEMA，并重新生成公开 Git |
| 对外框架和入口 | `public_app.py`、`public_entry.py` | 输出中性的 `shell.py`、`__main__.py` |
| 开发管理功能 | `app.py` | 不进入公开 Git |
| 阶段范围 | `../release_profiles.py` 与 `presentation.py` | 生成全部阶段稿；构建时裁剪源码、数据和依赖常量 |
| Excel 样稿 | `../excel_sample.mjs` | 同一快照导出；表内公式可编辑重算 |

计算口径见 [MARKET_INDICATORS.md](MARKET_INDICATORS.md)。
不要在生成目录手工维护另一套页面；构建器会拒绝覆盖手工改动。
界面源码更新需要接收方更新代码并重启，数据与自定义结果更新无需重启。

## 独立 Git 交付

如需同步所有阶段，优先运行 `../build_releases.cmd` 或点击 **生成全部阶段稿**。
50%、80%、1.0 分别维护独立公开 Git 历史，禁止把完整历史回退后用于较早阶段交付。
公开源码不包含阶段选择器、构建配方或内部维护文件。

在「数据与任务」点击 **生成看板发布 Git**，或在 project 目录运行：

```powershell
python dashboard/build_public_repository.py --demo-file "dashboard/runtime/published/demo.json" --bundle
```

默认输出 `dashboard/runtime/distribution/Delta1-market-dashboard`，含独立 main 与公共发布历史。
bundle 可离线交付；接收方使用 `git clone "文件.bundle" Delta1`。
构建审计全部公共历史，不复制父项目历史、远端、采集器、公式执行器、管理页面、配置或原始数据库。
这是 Python 3.12–3.14 桌面 App，尚不是免安装 exe。完整操作见 [PUBLIC_RELEASE.md](PUBLIC_RELEASE.md)。

## 数据发布与校验

开发端发布四品种 × 三频率的 12 个视图。数据、配置或公式改变后重算。
管理页面与私有回放期间仍维护最新发布；回放不会覆盖最新快照。
默认目录 `runtime/published`，可在「数据与任务」修改。
对方通过 `--publish-root` 或 `DELTA1_DATA_ROOT` 指定可读目录；本机旧入口仍接受 `SWHY_DELTA1_PUBLISH_ROOT`。

`current.json` 与 `demo.json` 分别为真实观察和合成示例，原子替换发布。
同频四品种完整验证后更新缓存，界面渲染不读取磁盘。
损坏、不兼容或超时保留末次结果；盘口、行情时刻单独检查过期。
离线合成示例不要求实时心跳，始终标为“合成演示”。
快照只含展示白名单；公式源码、参数、本机路径和原始异常不发布。

```powershell
python -B -s -m unittest discover -s tests -p 'test_native*.py' -v
```

覆盖回归前视、错时与缺口、事件去重、四列同代缓存、公式更新、回放隔离、独立 Git 历史及 bundle 克隆启动。
