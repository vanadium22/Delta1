"""Register the native Work Automation task without starting its mail/scheduler service."""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
from uuid import NAMESPACE_URL, uuid5

from ..config import ROOT


def find_work_automation(project=ROOT):
    project = Path(project).resolve()
    configured = os.environ.get("SWHY_WORK_AUTOMATION_ROOT")
    candidates = [Path(configured)] if configured else []
    for parent in project.parents:
        candidates.extend((parent/"work_automation", parent/"project/work_automation"))
    for folder in candidates:
        if (folder/"mail_app/work.py").is_file() and (folder/"mail_app/store.py").is_file():
            return folder.resolve()
    raise ValueError("未找到工作自动化工作台，请选择其包含app.py的目录。")


def register_task(work_root=None, project=ROOT):
    project = Path(project).resolve()
    work_root = Path(work_root).resolve() if work_root else find_work_automation(project)
    if not (work_root/"mail_app/work.py").is_file():
        raise ValueError("所选目录不是工作自动化工作台")
    sys.path.insert(0, str(work_root))
    try:
        Store = importlib.import_module("mail_app.store").Store
        WorkTasks = importlib.import_module("mail_app.work").WorkTasks
        # Constructors only initialize persistence; neither starts a worker or sends mail.
        tasks = WorkTasks(Store(work_root))
        program = project/"start_recent_brief_daily.cmd"
        existing = [t for t in tasks.tasks() if Path(t["program"]).resolve() == program]
        if len(existing) > 1:
            raise ValueError("已有多个同程序登记，请在工作台保留唯一任务后重试")
        if existing:
            task = existing[0]
            created = False  # Preserve the user's existing schedule, state and task identity.
        else:
            task = tasks.save({"id": "basis-"+uuid5(NAMESPACE_URL, os.path.normcase(str(program))).hex,
                "name": "股指基差每日Word与PDF简报", "program": str(program), "cwd": str(project.parent),
                "interpreter": "", "arguments": [], "enabled": True,
                "schedule": {"type": "weekdays", "time": "16:10"}, "result_mail": "off"})
            created = True
        return {"work_root": str(work_root), "task_id": task["id"], "created": created,
                "enabled": task["enabled"], "schedule": task["schedule"], "program": str(program)}
    finally:
        sys.path.remove(str(work_root))
