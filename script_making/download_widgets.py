"""Native file archive controls, deliberately separate from report analytics."""
import json
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
                              QWidget, QListWidget, QListWidgetItem)

from .downloads import DOWNLOADS, source_path
from .storage import ReportError
from .service import ALL_REPORTS
from .desktop_widgets import button, label


def open_location(path):
    target = Path(path)
    if not target.exists():
        raise ReportError("保存位置尚不存在，请先同步文件或检查本地保存目录。")
    try:
        if target.is_file() and os.name == "nt":
            subprocess.Popen(["explorer.exe", "/select,", str(target)],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent if target.is_file() else target))):
            raise ReportError("无法打开文件管理器，请检查系统设置。")
    except OSError as exc:
        raise ReportError("无法打开文件管理器，请检查保存路径。") from exc


class DownloadsDialog(QDialog):
    def __init__(self, service, start_download, parent=None):
        super().__init__(parent)
        self.service = service
        self.start_download = start_download
        self.panels = {}
        self.setWindowTitle("日报下载")
        self.resize(880, 570)
        layout = QVBoxLayout(self)
        layout.addWidget(label("日报下载", "dialogTitle"))
        layout.addWidget(label("全部已保存日报集中查看。互换/复核表配对同步；盈亏/策略台首次补近 7 天，之后增量补齐。", "muted", True))
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        for kind, spec in ALL_REPORTS.items():
            page = QWidget()
            body = QVBoxLayout(page)
            source = label("", "muted", True)
            try:
                value = (source_path(service.settings.get(), kind) if kind in DOWNLOADS
                         else service.settings.get().get("source_root") or "请在数据与同步中配置")
                source.setText("来源：" + str(value))
            except ReportError as exc:
                source.setText(str(exc))
            source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            body.addWidget(source)
            status = label("", "notice", True)
            status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            body.addWidget(status)
            files = QListWidget()
            body.addWidget(files, 1)
            destination = label("", "muted", True)
            destination.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            body.addWidget(destination)
            actions = QHBoxLayout()
            sync = button("检查并同步", lambda checked=False, key=kind: self.sync(key), "primary")
            reveal = button("打开保存位置", lambda checked=False, key=kind: self.reveal(key))
            actions.addWidget(sync)
            actions.addWidget(reveal)
            actions.addStretch()
            body.addLayout(actions)
            self.panels[kind] = {"files": files, "status": status, "sync": sync,
                                 "destination": destination, "fingerprint": None}
            tabs.addTab(page, spec["label"])
        self.error = label("", "error", True)
        self.error.hide()
        layout.addWidget(self.error)
        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.refresh)
        self.finished.connect(self.timer.stop)
        self.timer.start()
        self.refresh()

    def sync(self, kind):
        self.error.clear()
        self.error.hide()
        try:
            if kind not in DOWNLOADS and not self.service.settings.get().get("source_root"):
                raise ReportError("请先在「数据与同步」中设置共享来源目录。")
            self.start_download(kind)
        except ReportError as exc:
            self.error.setText(str(exc))
            self.error.show()
        self.panels[kind]["fingerprint"] = None
        self.refresh()

    def refresh(self):
        for kind, panel in self.panels.items():
            state = self.service.download_status(kind)
            fingerprint = json.dumps(state, sort_keys=True)
            panel["sync"].setEnabled(state["state"] != "running" and not getattr(self.parent(), "_closing", False))
            if fingerprint == panel["fingerprint"]:
                continue
            panel["fingerprint"] = fingerprint
            try:
                data = self.service.download_catalog(kind)
                panel["base"] = data["saved_dir"]
                panel["destination"].setText("保存位置：" + data["saved_dir"])
                current = panel["files"].currentItem()
                selected = current.data(Qt.ItemDataRole.UserRole) if current else None
                panel["files"].clear()
                for entry in data["files"]:
                    item = QListWidgetItem(f"{entry['date']}    {entry['name']}    {entry['size'] / 1024:,.1f} KB")
                    item.setData(Qt.ItemDataRole.UserRole, entry["path"])
                    panel["files"].addItem(item)
                    if entry["path"] == selected:
                        panel["files"].setCurrentItem(item)
                if panel["files"].currentRow() < 0 and panel["files"].count():
                    panel["files"].setCurrentRow(0)
                state = data["status"]
                result = state.get("result", {})
                latest = data["files"][0]["date"] if data["files"] else "尚无文件"
                text = f"本地最新日期：{latest}"
                if state["state"] == "running":
                    text += "\n正在检查并同步…"
                elif state["state"] == "error":
                    text += "\n" + state.get("error", "同步失败")
                elif result:
                    text += (f"\n配对报表检查完成 · {result.get('date', '')}" if kind not in DOWNLOADS else
                             f"\n{result.get('message', '检查完成')} · 新增 {len(result.get('saved', []))} 份 · 已有 {len(result.get('reused', []))} 份")
                    if result.get("source_latest"):
                        text += " · 本次发现最新 " + result["source_latest"]
                    if result.get("errors"):
                        text += "\n部分未完成：" + "；".join(result["errors"][:3])
                        panel["status"].setToolTip("\n".join(result["errors"]))
                if state.get("finished_at"):
                    text += "\n最后检查：" + state["finished_at"]
                panel["status"].setText(text)
            except (ReportError, OSError) as exc:
                panel["status"].setText(str(exc))

    def reveal(self, kind):
        panel = self.panels[kind]
        item = panel["files"].currentItem()
        path = item.data(Qt.ItemDataRole.UserRole) if item else panel.get("base")
        try:
            if not path:
                raise ReportError("保存位置尚未载入。")
            open_location(path)
            self.error.clear()
            self.error.hide()
        except ReportError as exc:
            self.error.setText(str(exc))
            self.error.show()
