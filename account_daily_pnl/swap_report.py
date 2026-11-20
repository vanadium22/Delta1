"""Check and locate the latest usable revenue swap daily report."""

import argparse
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys

from openpyxl import load_workbook

from dashboard.marketdata.trading_calendar import trading_days
from script_making.storage import ReportError, Settings, filename, save_files, sha256, today, validate_workbook
from shared_data.io import atomic_json


REPO = Path(__file__).resolve().parents[1]


def validate_swap(path, day):
    validate_workbook(path, "swap")
    book = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    try:
        if "收益总览" not in book.sheetnames:
            raise ReportError("收益互换日报缺少「收益总览」。")
        stamp = book["收益总览"]["K5"].value
        if isinstance(stamp, datetime):
            stamp = stamp.date()
        if isinstance(stamp, str):
            try:
                stamp = date.fromisoformat(stamp.strip())
            except ValueError:
                stamp = None
        if stamp != date.fromisoformat(day):
            raise ReportError(f"收益总览 K5 与文件名日期 {day} 不一致。")
    finally:
        book.close()


def sync_swap(settings, target):
    source = settings.get().get("source_root")
    if not source:
        raise ReportError("日报共享来源尚未配置。")
    notes = []
    for folder in sorted(Path(source).iterdir(), reverse=True):
        try:
            day = date.fromisoformat(folder.name).isoformat()
        except ValueError:
            continue
        if day != folder.name or day > target or not folder.is_dir():
            continue
        path = folder / filename("swap", day)
        if path.is_file():
            try:
                validate_swap(path, day)
            except (OSError, ValueError) as exc:
                notes.append(f"{day} 来源日报不可读：{exc}")
                continue
            archive = settings.data_path()
            result = save_files(archive, {"swap": path}, day, "共享目录下载", replace_existing=True)
            validate_swap(archive / day / path.name, day)
            result["warnings"] = notes
            return result
    raise ReportError(f"共享目录截至 {target} 尚无可读收益互换日报。{'；'.join(notes)}")


def check_swap(repo, target, *, local_only=False):
    repo = Path(repo)
    settings = Settings(repo / "script_making")
    base = settings.data_path()
    notes = []
    if not local_only:
        command = [sys.executable, "-X", "utf8", "-m", "account_daily_pnl.swap_report",
                   "--sync-only", "--date", target]
        try:
            result = subprocess.run(command, cwd=repo, capture_output=True, text=True, encoding="utf-8",
                                    timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            response = json.loads(result.stdout)
            if result.returncode or not response.get("ok"):
                notes.append("共享目录同步未完成：" + str(response.get("error", "同步失败")))
            else:
                notes.extend(response.get("warnings", []))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            notes.append("共享目录同步失败或超时，检查本地归档。")

    if base.is_dir():
        for folder in sorted(base.iterdir(), reverse=True):
            try:
                day = date.fromisoformat(folder.name).isoformat()
            except ValueError:
                continue
            if day != folder.name or day > target or not folder.is_dir():
                continue
            path = folder / filename("swap", day)
            if not path.is_file():
                continue
            try:
                fingerprint = sha256(path)
                validate_swap(path, day)
                if sha256(path) != fingerprint:
                    raise ReportError("读取期间文件发生变化。")
                if day < target:
                    notes.append(f"目标 {target} 的日报未就绪，使用 {day}。")
                return {"requested_date": target, "date": day, "path": str(path.resolve()),
                        "sha256": fingerprint, "size": path.stat().st_size, "notes": notes}
            except (OSError, ValueError) as exc:
                notes.append(f"{day} 日报不可读：{exc}")
    return {"requested_date": target, "date": None, "path": None, "notes": notes}


def main(argv=None):
    parser = argparse.ArgumentParser(description="检查收益互换日报更新")
    parser.add_argument("--date", help="截止交易日，默认前一交易日")
    parser.add_argument("--local-only", action="store_true", help="仅检查已有归档")
    parser.add_argument("--sync-only", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.date:
            target = date.fromisoformat(args.date).isoformat()
        else:
            _, target = trading_days("2025-12-30", today(), REPO / "data" / "account_daily_pnl" / "calendar")
        if args.sync_only:
            result = sync_swap(Settings(REPO / "script_making"), target)
            print(json.dumps({"ok": True, "warnings": result["warnings"]}, ensure_ascii=False))
            return 0
        result = check_swap(REPO, target, local_only=args.local_only)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["date"] else 2
    except (OSError, ValueError) as exc:
        if args.sync_only:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 1
        print(f"收益互换日报检查失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
