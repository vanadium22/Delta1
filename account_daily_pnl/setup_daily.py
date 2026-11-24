"""Configure and register the account report in the company's Work Automation."""

import importlib
import os
from pathlib import Path
import re
import sys
from uuid import NAMESPACE_URL, uuid5

from requests import ConnectionError, HTTPError, Timeout

from index_futures_basis.recent_brief.work_automation import find_work_automation
from index_strategy.history.protected_config import CredentialError, save_config

from .sources import ArchiveUnavailable, BctClient, bct_credential_path, login_values, protected_bct_path


TASK_NAME = "三账户场内持仓与盈亏"
DEFAULT_CLOCK = "09:25"


def task_definition(repo, data, output, config, clock):
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", clock):
        raise ValueError("日更时间请输入 HH:MM。")
    program = repo / "account_daily_pnl" / "workbench_entry.py"
    arguments = ["--no-pause", "--scheduled", "--data", str(data), "--output", str(output)]
    if config is not None:
        arguments.extend(("--config", str(Path(config).resolve())))
    return {
        "id": "account-pnl-" + uuid5(NAMESPACE_URL, os.path.normcase(str(program))).hex,
        "name": TASK_NAME, "program": str(program), "cwd": str(repo), "interpreter": sys.executable,
        "arguments": arguments, "enabled": True, "schedule": {"type": "daily", "time": clock},
        "auto_catch_up": True, "result_mail": "queue",
    }


def register_with_tasks(tasks, definition):
    same_program = Path(definition["program"]).resolve()
    old_program = same_program.with_name("start.cmd")
    existing = [item for item in tasks.tasks() if item["id"] == definition["id"] or item["name"] == TASK_NAME
                or Path(item["program"]).resolve() in (same_program, old_program)]
    if not existing:
        return tasks.save(definition), True
    if len(existing) != 1 or Path(existing[0]["program"]).resolve() not in (same_program, old_program):
        raise ValueError("工作台里已有同名或冲突的场内任务，请在定时子任务中核对其程序位置。")
    task = existing[0]
    updated = {**definition, "id": task["id"], "arguments": task.get("arguments", definition["arguments"]),
               "cwd": task.get("cwd", definition["cwd"])}
    return tasks.save(updated), False


def register_task(work_root, definition):
    if not (work_root / "mail_app" / "work.py").is_file() or not (work_root / "mail_app" / "store.py").is_file():
        raise ValueError("请选择已有的工作自动化工作台目录。")
    sys.path.insert(0, str(work_root))
    try:
        store = importlib.import_module("mail_app.store").Store
        work_tasks = importlib.import_module("mail_app.work").WorkTasks
        return register_with_tasks(work_tasks(store(work_root)), definition)
    finally:
        sys.path.remove(str(work_root))


def choose_bct_source():
    from PySide6.QtWidgets import QApplication, QFileDialog

    app = QApplication.instance() or QApplication([])
    filename, _ = QFileDialog.getOpenFileName(
        None, "请选择公司已有的 BCT 下载脚本或原始 1.zip", str(Path.home() / "Downloads"),
        "BCT 下载脚本或原始压缩包 (*.py *.zip)",
    )
    del app
    if not filename:
        raise ValueError("需要一次性选择 BCT 下载脚本或原始 1.zip，才能增量下载。")
    return Path(filename)


def input_directories(root):
    downloads = Path.home() / "Downloads"
    if os.name == "nt":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                value, _ = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")
                downloads = Path(os.path.expandvars(value))
        except (OSError, TypeError):
            pass
    module = Path(__file__).resolve().parent
    return (root / "inputs", module, module.parent, downloads, downloads / "Chrome",
            downloads / "IDM" / "Compressed")


def local_bct_source(root, *, allow_picker=True):
    for directory in input_directories(root):
        for filename in ("download_trading_flow_add_holdexcel.py", "download_trading_flow.py", "1.zip"):
            candidate = directory / filename
            if candidate.is_file():
                try:
                    login_values(candidate)
                except (OSError, ValueError, SyntaxError):
                    continue
                return candidate
    if allow_picker:
        return choose_bct_source()
    raise ValueError("找不到已有的 BCT 下载脚本，请在公司桌面双击收益统计.cmd 完成首次接入。")


def configure_credentials(root, config, override, *, allow_picker=True):
    source = bct_credential_path(root, config, override)
    protected = protected_bct_path(root)
    if source is not None and not Path(source).is_file():
        if override:
            raise ValueError("指定的 BCT 登录来源文件不存在。")
        source = None
    if source == protected:
        try:
            login_values(source)
        except (CredentialError, ValueError):
            source = None
    if source is None and not (os.environ.get("BCT_USERNAME") and os.environ.get("BCT_PASSWORD")):
        source = local_bct_source(root, allow_picker=allow_picker)
    print("正在验证公司 BCT 登录...", flush=True)
    try:
        client = BctClient(source)
        client.connect()
    except (ConnectionError, Timeout) as exc:
        raise ArchiveUnavailable("BCT 登录连接失败，请接通公司网络或 VPN 后重试。") from exc
    except HTTPError as exc:
        status = exc.response.status_code
        raise ValueError(f"BCT 登录返回 HTTP {status}。请核对旧脚本的登录设置和账户权限。") from exc
    if source != protected:
        username, password = login_values(source)
        save_config(protected, {"username": username, "password": password})
    print("BCT 登录已验证，已复用本机 Windows 用户的加密设置。", flush=True)
    return client


def configure_daily(repo, root, output, config, args):
    work_root = args.work_root.resolve() if args.work_root else find_work_automation(repo / "account_daily_pnl")
    definition = task_definition(repo, root, output, args.config, args.task_time)
    configure_credentials(root, config, args.bct_script)
    task, created = register_task(work_root, definition)
    print(f"{'已登记' if created else '已找到'}工作台任务：{task['name']}。", flush=True)
    print(f"计划：{task['schedule'].get('time', '见工作台')}（北京时间）；"
          f"当前{'启用' if task['enabled'] else '暂停'}；"
          f"错过后自动补跑{'开启' if task.get('auto_catch_up') else '关闭'}。", flush=True)
    print(f"工作台：{work_root}。收件人：meiyifan@swhysc.com。现在开始按实际交易日试跑。", flush=True)
