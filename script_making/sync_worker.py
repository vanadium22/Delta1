"""Bounded background copy entry point; does not load a GUI or HTTP server."""
import argparse
import json
from pathlib import Path

from .storage import ReportError, Settings, sync_reports


def main(argv=None):
    parser = argparse.ArgumentParser(description="同步本地日报")
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    settings = Settings(args.root)
    try:
        result = sync_reports(settings.get(), settings.data_path())
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
        return 0
    except (ReportError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
