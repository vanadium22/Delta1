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
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
