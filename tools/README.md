# 工作区维护工具

`workspace_cleanup.py` 只处理本仓库内已登记的旧开发验证产物，以及有 Git 跟踪源码可重建的 Python 字节码。正式应用、运行依赖、行情/缓存/配置/凭据、运行状态和其他 worktree 不在处理范围。

默认只盘点，不清理：

```powershell
python -B -X utf8 tools/workspace_cleanup.py
```

计划保存到忽略的 `local_artifacts/cleanup/plan-*.json`。只列入超过24小时的已知验证目录；近期结果、Git 跟踪文件、配置引用的目录、符号链接或重解析点保留。可通过 `--config <已有native.json>` 增加需要核验的外部配置引用，只读取、不改写。

核对计划后，明确指定刚生成的文件：

```powershell
python -B -X utf8 tools/workspace_cleanup.py --apply 'local_artifacts/cleanup/plan-日期时间.json'
```

执行先生成 ZIP，逐文件核验 SHA256，再核对每个源文件仍与计划相同，最后移除已经验证的旧副本；不使用递归强删。归档与原路径/哈希清单在 `local_artifacts/archives/validation/`，最近结果索引在 `local_artifacts/LATEST_CLEANUP.json`。源文件或配置发生变化时保留原件；中断后仍保留已验证归档。

归档含原 `.deps/` 相对路径与 `archive_manifest.json`。需要恢复时先解压到单独空目录，按原路径清单查找所需文件；不要直接覆盖现有工作区。新验证产物使用 `local_artifacts/validation/<任务日期>/`，保持 `.deps/` 主要用于运行依赖。
