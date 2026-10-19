# 对外市场看板源码发布

2026-10-02。此文件是项目内部维护说明，不进入对外 Git。

对外应用统一名为 **Delta1 市场看板**，包含「股指期货」「特殊指标」「市场异动」三个页面。公开源码只包含展示界面、主题、图标、启动支持和快照读取器；不包含公式执行器、采集器、管理页面、原始数据、私人配置或本项目 Git 历史。

## 生成与更新

在 `project` 目录执行：

```powershell
python -B -s -X utf8 dashboard/build_public_repository.py
```

默认生成 `dashboard/runtime/distribution/Delta1-market-dashboard`，是一个具有独立 `main` 分支及公共发布提交的本地 Git 仓库。首次创建新历史；以后执行同一命令，从当前共享代码重建并新增公共发布提交。没有代码变化时不产生空提交。此命令不创建远端、不推送任何内容、不修改父项目的 `.git`。

通过 `--demo-file` 显式加入合成示例，生成后仓库可以独立运行 `python -m dashboard --demo`。只允许 `demo: true` 且符合当前展示协议的快照；示例按展示白名单重新编码，去掉额外字段。

```powershell
python dashboard/build_public_repository.py --demo-file "dashboard/runtime/published/demo.json"
```

`--output` 可指定新的独立输出目录，`--archive` 可额外生成仅包含公共源码的 ZIP，`--no-commit` 可暂缓提交。兼容旧命令 `build_viewer_package.py` 也只生成当前公共源码 ZIP，不再打包管理界面的分支。

加 `--bundle` 会审核每个公共提交的文件和提交说明，然后生成 `Delta1-market-dashboard-<内容哈希>.bundle` 并运行 `git bundle verify`。此文件包含完整的公共 Git 历史，可离线交付。对方执行 `git clone "文件.bundle" Delta1` 后即可使用；里面没有父项目历史。`--bundle "完整输出路径"` 可指定保存位置。

如果公开输出目录的已生成文件被手工修改，构建器会停止以保留修改。应回到共享源修改界面，再重新生成；不要同时维护另一份界面源码。

## 共享源与输出边界

| 内容 | 内部唯一源 | 公开输出 |
| --- | --- | --- |
| 三个市场页面 | `native/market_view.py` | 同一页面逻辑 |
| 主题与图表 | `native/theme.py`、`native/widgets.py` | 删除未使用的 Python 代码编辑高亮类 |
| 只读应用框架 | `native/public_app.py` | `native/shell.py` |
| 只读启动入口 | `native/public_entry.py` | `native/__main__.py`，没有版本选择参数 |
| 发布读取协议 | `native/publication.py` | 抽取读取所需函数及类，输出类名 `MarketFeed` |
| 指标计算与自动发布 | `native/model.py`、`native/metrics.py`、`native/developer_model.py` 等 | 排除，应用仅消费结果 |

`release.json` 保存公共内容哈希及文件 SHA256。导出过程强制扫描公开文本中的版本关系文案、禁止的模块及项目本机路径，并检查 Python 语法与本地依赖边界。Git 提交只暂存生成白名单内的文件，不会带入额外本地文件。

## 验证

```powershell
python -B -s -m unittest discover -s tests -p 'test_native_public_repository.py' -v
```

检查独立 Git 历史、无父远端、内容哈希、自动使用共享源更新、本地修改保护、真实快照禁止嵌入、合成示例清理，以及从公开仓库克隆后独立启动。发布前同时运行现有原生界面及协议检查。
