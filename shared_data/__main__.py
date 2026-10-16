from __future__ import annotations

import argparse
import json
from pathlib import Path

from .catalog import Catalog
from .migration import MODULES, ensure_migrated, migration_plan
from .paths import DataPaths


def main():
    parser = argparse.ArgumentParser(description="Delta1 公共本地数据目录")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--data-root", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("paths")
    commands.add_parser("catalog")
    migration = commands.add_parser("migrate")
    migration.add_argument("--module", choices=MODULES, action="append")
    migration.add_argument("--apply", action="store_true")
    migration.add_argument("--summary", action="store_true", help="显示一键迁移的简明结果")
    prune = commands.add_parser("prune")
    prune.add_argument("dataset")
    prune.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    paths = DataPaths.for_repo(args.repo_root, data_root=args.data_root)
    if args.command == "paths":
        result = {"data_root": str(paths.root), "outputs_root": str(paths.outputs)}
    elif args.command == "catalog":
        result = [{"key": d.key, "path": str(Catalog(paths).get(d.key)[1]), "retention": d.retention} for d in Catalog(paths).list()]
    elif args.command == "prune":
        result = Catalog(paths).prune(args.dataset, apply=args.apply)
    else:
        result = []
        for module in args.module or MODULES:
            root = paths.repo_root / module
            if args.apply:
                result.append(ensure_migrated(module, root, paths))
            else:
                result.append({"module": module, "files": [{"source": str(m["source"]), "destination": str(m["destination"])}
                                                         for m in migration_plan(module, root, paths)]})
    if args.command == "migrate" and args.summary:
        print(f"公共数据目录：{paths.root}")
        print("模式：复制并校验，原文件保留" if args.apply else "模式：仅预览，不复制文件")
        labels = {"index_futures_basis": "股指基差", "script_making": "日报", "securities_lending": "券单"}
        for item in result:
            files = item["files"]
            rejected = sum(bool(f.get("rejected_manifest")) for f in files)
            print(f"{labels[item['module']]}：{len(files)} 个文件/清单" + (f"；{rejected} 个旧清单无效，已隔离保留" if rejected else ""))
        if args.apply:
            print(f"迁移完成。核验记录：{paths.root / '_migrations'}")
            print("重复运行会复用已完成的迁移记录；不会用旧文件覆盖公共目录。")
            print("请使用更新后的三个 App。以后新分红请放公共分红目录或在 App 中导入。")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
