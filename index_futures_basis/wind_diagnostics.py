"""Company Wind diagnosis, with copyable evidence and an isolated sync database."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import date, datetime, timedelta
import importlib.metadata
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import traceback
import uuid

from .config import ROOT, SHANGHAI, atomic_json, closed_date, load_config
from .wind import WindProvider
from .wind_worker import CALENDAR_OPTIONS
from shared_data import DataPaths


class Report:
    def __init__(self, output, metadata):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        self.data = {"schema_version": 1, "metadata": metadata, "checks": [], "requests": [], "finished": False}
        self.save()

    def text(self):
        counts = {status: sum(c["status"] == status for c in self.data["checks"])
                  for status in ("PASS", "FAIL", "SKIP", "RUNNING")}
        lines = ["===== Delta1 Wind 诊断：请从这里完整复制 =====",
                 "PASS=通过；FAIL=失败；SKIP=未覆盖。检查失败也请保留整份结果。",
                 "检查汇总：" + json.dumps(counts, ensure_ascii=False),
                 "补缺仅在本次独立诊断库进行，正式行情库未修改。",
                 json.dumps(self.data["metadata"], ensure_ascii=False, indent=2)]
        for check in self.data["checks"]:
            lines += ["", f"[{check['status']}] {check['name']}"]
            lines += [f"  {key}: {json.dumps(value, ensure_ascii=False)}"
                      for key, value in check.get("detail", {}).items()]
            if check.get("error"):
                lines += [check["error"], check["traceback"]]
        failed = [r for r in self.data["requests"] if r.get("error")]
        lines += ["", f"已记录请求 {len(self.data['requests'])} 次；失败 {len(failed)} 次"]
        for item in failed:
            lines.append(json.dumps(item, ensure_ascii=False))
        lines += [f"完成状态：{self.data['finished']}", "===== Delta1 Wind 诊断结束 ====="]
        return "\n".join(lines) + "\n"

    def save(self):
        atomic_json(self.output / "diagnostic.json", self.data)
        text_path = self.output / "可复制.txt"
        temporary = text_path.with_suffix(".tmp")
        temporary.write_text(self.text(), encoding="utf-8-sig")
        temporary.replace(text_path)

    def check(self, name, operation):
        entry = {"name": name, "status": "RUNNING", "detail": {}}
        self.data["checks"].append(entry)
        self.save()
        print(f"正在检查：{name}", flush=True)
        started = time.monotonic()
        try:
            result = operation(entry["detail"])
            entry["status"] = "PASS"
            return result
        except Exception as exc:
            entry.update(status="FAIL", error=f"{type(exc).__name__}: {exc}"[:3000],
                         traceback=traceback.format_exc(limit=8))
            return None
        finally:
            entry["elapsed_seconds"] = round(time.monotonic() - started, 3)
            self.save()
            print(f"[{entry['status']}] {name}", flush=True)

    def skip(self, name, reason):
        self.data["checks"].append({"name": name, "status": "SKIP", "detail": {"reason": reason}})
        self.save()

    def finish(self):
        self.data["finished"] = True
        self.save()
        (self.output.parent / "latest.txt").write_text(self.text(), encoding="utf-8-sig")
        atomic_json(self.output.parent / "latest.json", {"folder": str(self.output),
                                                      "text": str(self.output / "可复制.txt")})
        return 0 if all(c["status"] == "PASS" for c in self.data["checks"]) else 2


class DiagnosticProvider(WindProvider):
    worker_filename = "diagnostic_worker.py"

    def __init__(self, config, report, timeout, budget):
        super().__init__(dict(config))
        self.report, self.timeout = report, timeout
        self.deadline = time.monotonic() + budget
        self.blocked = None

    def request(self, operation, **kwargs):
        started = time.monotonic()
        item = {"operation": operation, "arguments": kwargs}
        self.report.data["requests"].append(item)
        try:
            if self.blocked:
                raise ConnectionError("后续连接检查已跳过：" + self.blocked)
            remaining = self.deadline - started
            if remaining <= 0:
                raise TimeoutError("已达到诊断总时限，已完成证据仍保存在结果目录")
            self.config["wind_timeout_seconds"] = min(self.timeout, remaining)
            result = super().request(operation, **kwargs)
            # Only shape and coverage are logged here, never quote values.
            item["result_items"] = len(result) if isinstance(result, (dict, list)) else None
            return result
        except Exception as exc:
            item["error"] = f"{type(exc).__name__}: {exc}"[:3000]
            if isinstance(exc, (ConnectionError, TimeoutError)):
                self.blocked = item["error"]
            raise
        finally:
            item["elapsed_seconds"] = round(time.monotonic() - started, 3)
            self.report.save()


def git_version(root):
    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True,
                                text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return result.stdout.strip() if result.returncode == 0 else "未知"
    except (OSError, subprocess.TimeoutExpired):
        return "未知"


def local_database(root, paths, config):
    market = paths.root / "market" / "index_futures"
    base = paths.resolve_module_setting(root, config["data_directory"], market, ("data",))
    return (paths.basis("wind") if base == market else base / "wind") / "market.sqlite"


def database_info(path):
    info = {"path": str(path), "exists": path.is_file(), "access": "只读"}
    if path.is_file():
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
            info["quotes"] = con.execute("SELECT count(*) FROM quotes").fetchone()[0]
            info["latest_by_root"] = dict(con.execute(
                "SELECT substr(code,1,2),max(day) FROM quotes WHERE code GLOB '*[.]CFE' GROUP BY substr(code,1,2)"))
            info["calendar_days"] = con.execute("SELECT count(*) FROM calendar").fetchone()[0]
            row = con.execute("SELECT value FROM meta WHERE key='calendar_verification'").fetchone()
            verification = json.loads(row[0]) if row else {}
            info["verified_calendar_options"] = verification.get("options")
            info["verified_calendar_dates"] = len(verification.get("dates", []))
    return info


def check_calendar(provider, detail, first, last, *, closed=False):
    detail["raw"] = provider.request("diagnostic_calendar", start=first, end=last)
    days = provider.calendar(first, last)
    detail.update(normalized_count=len(days), first=days[0] if days else None, last=days[-1] if days else None)
    raw = detail["raw"]["tdayscount"]
    data = raw.get("data_sample", [])
    count = data[0][0] if len(data) == 1 and len(data[0]) == 1 else None
    if (raw.get("error_code") != 0 or isinstance(count, bool) or not isinstance(count, (int, float))
            or count != len(days)):
        raise ValueError("TDAYSCOUNT与规范化日期数量不一致，见raw原始结构及错误码")
    if closed and days:
        raise ValueError("该样例被Wind判为开市，不能作为休市通过；见日期范围和返回值")
    return days


def run_checks(report, config, paths, root, cutoff, timeout=25, budget=180, holiday_date=None, provider=None):
    provider = provider or DiagnosticProvider(config, report, timeout, budget)
    try:
        def environment(detail):
            detail.update(provider.request("diagnostic_environment"))
            if detail.get("connected") is False:
                raise ConnectionError("Wind终端未连接，请先登录终端")
        report.check("Python / WindPy / 终端连接", environment)
        report.check("正式本地库概况（只读）",
                     lambda detail: detail.update(database_info(local_database(root, paths, config))))
        first = (cutoff - timedelta(days=89)).isoformat()
        def recent(detail):
            days = check_calendar(provider, detail, first, cutoff.isoformat())
            if not days:
                raise ValueError("最近90个自然日均无交易日，不能据此选择行情补缺日期")
            return days
        days = report.check("近期90天交易日历及数量一致性", recent)
        sunday = cutoff - timedelta(days=(cutoff.weekday() + 1) % 7)
        report.check("最近完整周末：正常零交易日",
                     lambda detail: check_calendar(provider, detail, (sunday - timedelta(days=1)).isoformat(),
                                                   sunday.isoformat(), closed=True))
        if holiday_date:
            holiday = holiday_date.isoformat()
        elif days:
            opened = set(days)
            holiday = next((d.isoformat() for i in range(90)
                            if (d := cutoff - timedelta(days=i)).weekday() < 5 and d.isoformat() not in opened), None)
        else:
            holiday = None
        if holiday:
            report.check("休市工作日样例：Wind确认零交易日",
                         lambda detail: check_calendar(provider, detail, holiday, holiday, closed=True))
        else:
            report.skip("休市工作日样例", "未找到已验证的休市工作日，可加--holiday-date指定样例")
        if not days:
            report.skip("行情补缺与缓存复用", "没有可靠交易日历，未猜日期或请求行情")
            return

        # Exercise the production sync algorithm in a new, isolated database.
        from .store import Store
        from .sync import synchronize
        probe = Store(report.output / "probe.sqlite")
        session = days[-1]
        progress = lambda message: print(message, flush=True)
        def initial(detail):
            detail.update(synchronize(probe, provider, session, session, progress))
            detail["probe_date"] = session
            if detail["state"] != "complete":
                raise ValueError("单日四品种行情未完整补齐，见errors与请求记录")
            return True
        if not report.check("独立库：最近完整交易日首次补齐", initial):
            report.skip("缓存复用 / 单字段补缺", "首次补齐未完成，避免把部分数据冒充通过")
            return
        def repeat(detail):
            before = len(report.data["requests"])
            detail.update(synchronize(probe, provider, session, session, progress))
            detail["actual_provider_requests"] = len(report.data["requests"]) - before
            if detail["requests"] or detail["actual_provider_requests"] or detail["state"] != "complete":
                raise ValueError("完整缓存仍触发请求或存在缺失")
        report.check("独立库：重复检查零行情请求", repeat)
        def repair(detail):
            code = probe.mappings(session, session)[(session, "IF", 1)]
            before = probe.quotes(session, session)
            # Deliberately remove one OI cell only from this diagnostic database.
            with probe.connection() as con:
                con.execute("DELETE FROM quotes WHERE code=? AND day=? AND field='oi'", (code, session))
            before.pop((code, session, "oi"))
            mark = len(report.data["requests"])
            detail.update(synchronize(probe, provider, session, session, progress))
            calls = report.data["requests"][mark:]
            detail["repair_cell"] = {"code": code, "date": session, "field": "oi"}
            detail["requests_for_repair"] = calls
            after = probe.quotes(session, session)
            restored = after.pop((code, session, "oi"), None)
            if (detail["state"] != "complete" or restored is None or after != before or len(calls) != 1
                    or calls[0]["operation"] != "series" or calls[0]["arguments"].get("fields") != ["oi"]
                    or calls[0]["arguments"].get("code") != code):
                raise ValueError("单字段补缺未达到仅请求缺失OI且保持其余数据不变")
        report.check("独立库：仅补一个缺失持仓字段", repair)
    finally:
        provider.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Wind日历、休市和行情补缺诊断；不修改正式行情库")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--as-of", type=date.fromisoformat, help="指定诊断截止日期，默认北京时间已收盘截止日")
    parser.add_argument("--holiday-date", type=date.fromisoformat, help="指定希望验证的休市日")
    parser.add_argument("--output", type=Path, help="诊断结果父目录，默认公共data/diagnostics/index_futures_basis")
    parser.add_argument("--timeout", type=float, default=25, help="每批请求最多等待秒数，默认25")
    parser.add_argument("--max-seconds", type=float, default=180, help="联网诊断总预算秒数，默认180")
    parser.add_argument("--no-pause", action="store_true", help="供CMD入口使用，不在结束后等待按键")
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 120 or not 1 <= args.max_seconds <= 600:
        parser.error("timeout须为1—120秒，max-seconds须为1—600秒")
    root = args.root.resolve()
    # If a local path configuration is damaged, still save a readable setup error.
    fallback = root.parent if root.name == "index_futures_basis" else root
    parent = args.output or fallback / "data/diagnostics/index_futures_basis"
    paths_error = None
    try:
        paths = DataPaths.for_module(root)
        if args.output is None:
            parent = paths.root / "diagnostics/index_futures_basis"
    except Exception as exc:
        paths_error = exc
    now = datetime.now(SHANGHAI)
    folder = Path(parent).resolve() / (now.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6])
    packages = {}
    for name in ("pandas", "numpy", "PySide6-Essentials"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "未安装"
    report = Report(folder, {"time_beijing": now.isoformat(), "git_commit": git_version(root),
                            "app_python": sys.executable, "packages": packages, "calendar_options": CALENDAR_OPTIONS,
                            "probe_database": str(folder / "probe.sqlite")})
    print(f"诊断结果目录：{folder}", flush=True)
    try:
        if paths_error:
            raise paths_error
        config = load_config(root)
        closed_cutoff = date.fromisoformat(closed_date(config))
        cutoff = args.as_of or closed_cutoff
        if cutoff > closed_cutoff or (args.holiday_date and args.holiday_date > cutoff):
            raise ValueError(f"诊断截止日不能晚于已收盘截止日{closed_cutoff}，节假日样例不能晚于截止日")
        if args.holiday_date and args.holiday_date.weekday() >= 5:
            raise ValueError("节假日样例请选择周一至周五的休市日期；周末由独立步骤检查")
        report.data["metadata"].update(cutoff=cutoff.isoformat(), wind_python=config.get("wind_python") or sys.executable,
                                       mapping_field=config["wind_mapping_field"], expiry_field=config["wind_expiry_field"])
        run_checks(report, config, paths, root, cutoff, args.timeout, args.max_seconds, args.holiday_date)
    except Exception as exc:
        def failure(detail):
            raise exc
        report.check("诊断配置或执行异常", failure)
    code = report.finish()
    print(report.text())
    print(f"请复制此文件全部内容：{folder / '可复制.txt'}")
    print(f"最近一次结果：{folder.parent / 'latest.txt'}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
