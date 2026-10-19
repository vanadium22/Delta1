"""Bounded background copy entry point; does not load a GUI or HTTP server."""
import argparse
import json
from pathlib import Path

from .storage import ReportError, Settings, sync_reports


def main(argv=None):
    parser = argparse.ArgumentParser(description="同步本地日报")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--only-missing", action="store_true")
    args = parser.parse_args(argv)
    settings = Settings(args.root)
    try:
        result = sync_reports(settings.get(), settings.data_path(), only_missing=args.only_missing)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
        return 0
    except (ReportError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
