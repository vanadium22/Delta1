"""Native widgets on the main thread; collection and disk writes in the service."""
from __future__ import annotations

from datetime import datetime
import logging
import os
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk

from ..instant_dld.service import ACTIVE_STATES, DownloadService, write_json
from ..instant_dld.symbols import load_symbols, parse_symbols
from ..instant_dld.quotes import CHINA
from .tables import DataTable

BG = "#F3F6F8"
NAV = "#132B3A"
INK = "#182F3D"
MUTED = "#72818D"
LINE = "#E3E9EE"
TEAL = "#087F78"
FONT = "Microsoft YaHei UI" if sys.platform == "win32" else "sans-serif"


def clock_text(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value).astimezone(CHINA).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value


class Delta1App(ctk.CTk):
    def __init__(self, service: DownloadService | None = None):
        self.service = service if service is not None else DownloadService()
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        super().__init__()
        self.title("Delta1 · 指数策略工作台")
        self.geometry("1400x820")
        self.minsize(1120, 760)
        self.configure(fg_color=BG)
        self.protocol("WM_DELETE_WINDOW", self.request_close)
        self._closing = False
        self._poll_id = None
        self._cursor = 0
        self._busy = None
        self._last_error = None
        self._quote_cursor = 0
        self._quote_run = None
        self._page = "realtime"
        self.interval = tk.StringVar(self)
        self.output_dir = tk.StringVar(self)
        self.autoscroll = tk.BooleanVar(self, True)
        self.display_symbol = tk.StringVar(self)
        self.editable = []
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self._build_sidebar()
        self._build_workspace()
        self.set_form(self.service.config())
        self.refresh()

    @staticmethod
    def label(parent, text, *, size=13, bold=False, color=INK, **kwargs):
        kwargs.setdefault("anchor", "w")
        kwargs.setdefault("height", max(18, size + 6))
        return ctk.CTkLabel(parent, text=text, font=(FONT, size, "bold" if bold else "normal"),
                            text_color=color, **kwargs)

    @staticmethod
    def button(parent, text, command, *, primary=False, **kwargs):
        kwargs.setdefault("height", 36)
        return ctk.CTkButton(parent, text=text, command=command, corner_radius=7,
                             font=(FONT, 13), fg_color=TEAL if primary else "#EEF3F6",
                             text_color="white" if primary else INK,
                             hover_color="#06665F" if primary else "#DDE8EE", **kwargs)

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(self, width=202, fg_color=NAV, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(5, weight=1)
        self.label(sidebar, "D / 1", size=31, bold=True, color="white").grid(
            row=0, column=0, sticky="w", padx=25, pady=(32, 0))
        self.label(sidebar, "指数策略工作台", color="#9CB4C2").grid(
            row=1, column=0, sticky="w", padx=25, pady=(0, 39))
        self.label(sidebar, "数据下载", size=12, color="#89A4B5").grid(
            row=2, column=0, sticky="w", padx=25, pady=(0, 12))
        self.nav_realtime = ctk.CTkButton(
            sidebar, text="实时下载", anchor="w", height=43, font=(FONT, 14, "bold"),
            fg_color="#21525A", hover_color="#2B6067", command=lambda: self.show_page("realtime"))
        self.nav_realtime.grid(row=3, column=0, padx=14, pady=3, sticky="ew")
        self.nav_trading = ctk.CTkButton(
            sidebar, text="交易数据下载", anchor="w", height=43, font=(FONT, 14),
            fg_color="transparent", hover_color="#244352", text_color="#ADC1CD",
            command=lambda: self.show_page("trading"))
        self.nav_trading.grid(row=4, column=0, padx=14, pady=3, sticky="ew")
        self.label(sidebar, "SWHY  /  DELTA1", size=12, bold=True, color="#CFDEE6").grid(
            row=6, column=0, padx=25, pady=(0, 4), sticky="w")
        self.label(sidebar, "本地桌面应用", size=11, color="#89A4B5").grid(
            row=7, column=0, padx=25, pady=(0, 24), sticky="w")

    def _build_workspace(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, padx=26, pady=23, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(3, weight=1)
        self.label(main, "工作台  /  数据下载", size=12, color=MUTED).grid(row=0, column=0, sticky="w")
        heading = ctk.CTkFrame(main, fg_color="transparent")
        heading.grid(row=1, column=0, sticky="ew", pady=(8, 18))
        heading.grid_columnconfigure(0, weight=1)
        self.page_title = self.label(heading, "实时数据下载", size=26, bold=True)
        self.page_title.grid(row=0, column=0, sticky="w")
        self.page_subtitle = self.label(heading, "配置采集任务，持续保存最新行情。", color=MUTED)
        self.page_subtitle.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.status_label = self.label(heading, "●  待启动", size=12, bold=True,
                                       color=TEAL, fg_color="#E5F2EF", corner_radius=8, width=120, anchor="center")
        self.status_label.grid(row=0, column=1, rowspan=2, padx=(14, 0))
        self.metrics = ctk.CTkFrame(main, fg_color="transparent")
        self.metrics.grid(row=2, column=0, sticky="ew", pady=(0, 18))
        self.metrics.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="metric")
        self.metric_values = {}
        for column, (key, name) in enumerate((("symbols", "标的数量"), ("polls", "采集轮数"),
                                             ("batches", "已保存批次"), ("latency", "最近响应耗时"))):
            card = ctk.CTkFrame(self.metrics, fg_color="white", corner_radius=10, border_width=1, border_color=LINE)
            card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 6, 0 if column == 3 else 6))
            self.label(card, name, size=12, color=MUTED).pack(anchor="w", padx=17, pady=(12, 0))
            value = self.label(card, "—", size=26, bold=True)
            value.pack(anchor="w", padx=17, pady=(2, 10))
            self.metric_values[key] = value
        self.realtime_page = ctk.CTkFrame(main, fg_color="transparent")
        self.realtime_page.grid(row=3, column=0, sticky="nsew")
        self.realtime_page.grid_columnconfigure(0, weight=1, minsize=340)
        self.realtime_page.grid_columnconfigure(1, weight=3, minsize=420)
        self.realtime_page.grid_rowconfigure(0, weight=1)
        self._build_configuration()
        self._build_monitor()
        self.trading_page = ctk.CTkFrame(main, fg_color="white", corner_radius=12, border_width=1, border_color=LINE)
        self.label(self.trading_page, "交易数据下载", size=22, bold=True).pack(anchor="w", padx=32, pady=(35, 12))
        self.label(self.trading_page, "此模块将在后续接入。", size=15).pack(anchor="w", padx=32)
        self.label(self.trading_page, "当前可使用「实时下载」配置和运行行情采集。", color=MUTED).pack(
            anchor="w", padx=32, pady=10)
        self.button(self.trading_page, "进入实时下载", lambda: self.show_page("realtime"), primary=True).pack(
            anchor="w", padx=32, pady=18)
        self.footer = self.label(main, "行情需要公司内网或 VPN 连接。", size=11, color=MUTED)
        self.footer.grid(row=4, column=0, sticky="w", pady=(11, 0))

    def _build_configuration(self):
        card = ctk.CTkFrame(self.realtime_page, fg_color="white", corner_radius=12, border_width=1, border_color=LINE)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(3, weight=1, minsize=110)
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 10))
        header.grid_columnconfigure(0, weight=1)
        self.label(header, "采集配置", size=17, bold=True).grid(row=0, column=0, sticky="w")
        self.save_button = self.button(header, "保存配置", self.save_config, width=86, height=30)
        self.save_button.grid(row=0, column=1)
        self.editable.append(self.save_button)
        self.label(card, "标的列表", bold=True).grid(row=1, column=0, padx=20, sticky="w")
        self.label(card, "每行一个代码，或粘贴 list；自动去重。", size=11, color=MUTED).grid(
            row=2, column=0, padx=20, pady=(0, 5), sticky="w")
        self.symbols = ctk.CTkTextbox(card, height=120, font=("Consolas", 14), fg_color="#F7F9FB",
                                      border_width=1, border_color=LINE, corner_radius=7, wrap="word", undo=True)
        self.symbols.grid(row=3, column=0, padx=20, sticky="nsew")
        self.symbols.bind("<KeyRelease>", self._update_symbol_count)
        self.editable.append(self.symbols)
        imports = ctk.CTkFrame(card, fg_color="transparent")
        imports.grid(row=4, column=0, padx=20, pady=(8, 12), sticky="ew")
        self.import_button = self.button(imports, "导入文件", self.import_symbols, width=91, height=29)
        self.import_button.pack(side="left")
        self.export_button = self.button(imports, "导出列表", self.export_symbols, width=91, height=29)
        self.export_button.pack(side="left", padx=(8, 0))
        self.editable.extend([self.import_button, self.export_button])
        interval_row = ctk.CTkFrame(card, fg_color="transparent")
        interval_row.grid(row=5, column=0, padx=20, pady=(0, 12), sticky="ew")
        interval_row.grid_columnconfigure(0, weight=1)
        self.label(interval_row, "采集间隔", bold=True).grid(row=0, column=0, sticky="w")
        self.label(interval_row, "支持小数，例如 0.5 秒", size=11, color=MUTED).grid(row=1, column=0, sticky="w")
        self.interval_entry = ctk.CTkEntry(interval_row, textvariable=self.interval, width=82, height=36,
                                           border_color=LINE, fg_color="#F7F9FB", font=(FONT, 14))
        self.interval_entry.grid(row=0, column=1, rowspan=2, padx=(8, 8))
        self.label(interval_row, "秒").grid(row=0, column=2, rowspan=2)
        self.editable.append(self.interval_entry)
        self.label(card, "数据保存位置", bold=True).grid(row=6, column=0, padx=20, sticky="w")
        directory = ctk.CTkFrame(card, fg_color="transparent")
        directory.grid(row=7, column=0, padx=20, pady=(5, 5), sticky="ew")
        directory.grid_columnconfigure(0, weight=1)
        self.output_entry = ctk.CTkEntry(directory, textvariable=self.output_dir, height=36,
                                         border_color=LINE, fg_color="#F7F9FB", font=(FONT, 12))
        self.output_entry.grid(row=0, column=0, sticky="ew")
        self.browse_button = self.button(directory, "选择…", self.choose_directory, width=64)
        self.browse_button.grid(row=0, column=1, padx=(7, 0))
        self.editable.extend([self.output_entry, self.browse_button])
        self.label(card, "Parquet · 按标的 / 年 / 月归档", size=11, color=MUTED).grid(
            row=8, column=0, padx=20, pady=(0, 8), sticky="w")
        self.feedback = self.label(card, "准备就绪，点击开始采集。", size=11, color=TEAL, wraplength=340, justify="left")
        self.feedback.grid(row=9, column=0, padx=20, pady=(0, 9), sticky="ew")
        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=10, column=0, padx=20, pady=(0, 18), sticky="ew")
        actions.grid_columnconfigure((0, 1), weight=1)
        self.start_button = self.button(actions, "开始采集", self.start_collection, primary=True)
        self.start_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.stop_button = self.button(actions, "停止采集", self.stop_collection, state="disabled")
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=(5, 0))

    def _build_monitor(self):
        monitor = ctk.CTkFrame(self.realtime_page, fg_color="transparent")
        monitor.grid(row=0, column=1, sticky="nsew", padx=(9, 0))
        monitor.grid_columnconfigure(0, weight=1)
        monitor.grid_rowconfigure((0, 1), weight=1, uniform="monitor")
        overall = ctk.CTkFrame(monitor, fg_color="white", corner_radius=12, border_width=1, border_color=LINE)
        overall.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        overall.grid_columnconfigure(0, weight=1)
        overall.grid_rowconfigure(2, weight=1)
        header = ctk.CTkFrame(overall, fg_color="transparent")
        header.grid(row=0, column=0, padx=16, pady=(14, 6), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        self.label(header, "整体运行情况", size=17, bold=True).grid(row=0, column=0, sticky="w")
        self.button(header, "清空记录", self.clear_logs, width=80, height=28).grid(row=0, column=1)
        tools_row = ctk.CTkFrame(overall, fg_color="transparent")
        tools_row.grid(row=1, column=0, padx=16, pady=(0, 6), sticky="ew")
        tools_row.grid_columnconfigure(0, weight=1)
        self.result_label = self.label(tools_row, "成功 0  /  异常 0", size=11, color=MUTED)
        self.result_label.grid(row=0, column=0, sticky="w")
        ctk.CTkSwitch(tools_row, text="自动滚动", variable=self.autoscroll, font=(FONT, 11),
                       width=95, switch_width=28, switch_height=16, progress_color=TEAL).grid(row=0, column=1)
        self.status_table = DataTable(overall, [("timestamp", "时间", 153), ("status", "结果", 62),
            ("description", "情况说明", 290), ("failed", "失败标的", 165)], font_family=FONT)
        self.status_table.tree.configure(displaycolumns=("timestamp", "status", "failed", "description"))
        self.status_table.grid(row=2, column=0, padx=14, sticky="nsew")
        self.status_detail = self.label(overall, "选择一行查看摘要，双击查看完整说明。", size=11, color=MUTED,
                                        wraplength=420, justify="left", height=36)
        self.status_detail.grid(row=3, column=0, padx=16, pady=(3, 8), sticky="ew")
        self.status_table.tree.bind("<<TreeviewSelect>>", self.show_status_detail)
        self.status_table.tree.bind("<Double-1>", self.show_report_window)
        quotes = ctk.CTkFrame(monitor, fg_color="white", corner_radius=12, border_width=1, border_color=LINE)
        quotes.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        quotes.grid_columnconfigure(0, weight=1)
        quotes.grid_rowconfigure(2, weight=1)
        quote_header = ctk.CTkFrame(quotes, fg_color="transparent")
        quote_header.grid(row=0, column=0, padx=16, pady=(14, 6), sticky="ew")
        quote_header.grid_columnconfigure(0, weight=1)
        self.label(quote_header, "标的行情", size=17, bold=True).grid(row=0, column=0, sticky="w")
        self.symbol_selector = ctk.CTkOptionMenu(quote_header, variable=self.display_symbol, values=["—"],
            command=self.select_symbol, width=136, height=29, font=(FONT, 12), fg_color=TEAL, button_color="#06665F")
        self.symbol_selector.grid(row=0, column=1)
        self.label(quotes, "行时间为采集时间；行情时间为接口原值。文件保留五档。", size=11, color=MUTED).grid(
            row=1, column=0, padx=16, pady=(0, 5), sticky="w")
        self.quote_table = DataTable(quotes, [("timestamp", "采集时间", 153), ("close", "最新价", 64),
            ("volume_total", "累计成交量", 94), ("volume", "区间成交量", 88),
            ("bid_price_1", "买一价", 64), ("bid_volume_1", "买一量", 82),
            ("ask_price_1", "卖一价", 64), ("ask_volume_1", "卖一量", 82),
            ("quote_time", "行情时间", 78)], font_family=FONT, limit=200)
        self.quote_table.tree.configure(displaycolumns=("timestamp", "close", "volume_total", "bid_price_1",
            "bid_volume_1", "ask_price_1", "ask_volume_1", "volume", "quote_time"))
        self.quote_table.grid(row=2, column=0, padx=14, sticky="nsew")
        details = ctk.CTkFrame(quotes, fg_color="transparent")
        details.grid(row=3, column=0, padx=16, pady=(6, 10), sticky="ew")
        details.grid_columnconfigure(0, weight=1)
        self.response_label = self.label(details, "最近响应  —", size=11, color=MUTED)
        self.response_label.grid(row=0, column=0, sticky="w")
        self.button(details, "打开文件夹", self.open_output, width=95, height=28).grid(row=0, column=1)

    def show_status_detail(self, _event=None):
        selection = self.status_table.tree.selection()
        if selection:
            values = self.status_table.tree.item(selection[0], "values")
            detail = f"{values[0]}  {values[2]}" + (f"；失败：{values[3]}" if values[3] != "—" else "")
            self.status_detail.configure(text=detail[:140] + ("…" if len(detail) > 140 else ""))

    def select_symbol(self, _value=None):
        self._quote_cursor = 0
        self.quote_table.clear()
        self._refresh_quotes()

    def show_report_window(self, _event=None):
        selection = self.status_table.tree.selection()
        if not selection:
            return
        values = self.status_table.tree.item(selection[0], "values")
        window = ctk.CTkToplevel(self)
        window.title("运行详情")
        window.geometry("660x330")
        window.transient(self)
        text = ctk.CTkTextbox(window, font=(FONT, 13), wrap="word")
        text.pack(fill="both", expand=True, padx=16, pady=16)
        text.insert("1.0", f"时间：{values[0]}\n结果：{values[1]}\n失败标的：{values[3]}\n\n{values[2]}")
        text.configure(state="disabled")

    def _refresh_quotes(self):
        rows = self.service.quote_snapshot(self.display_symbol.get(), self._quote_cursor)
        columns = ["close", "volume_total", "volume", "bid_price_1", "bid_volume_1", "ask_price_1", "ask_volume_1"]
        for row in rows:
            timestamp = datetime.fromtimestamp(row["timestamp"], CHINA).strftime("%Y-%m-%d %H:%M:%S")
            values = [timestamp, *["—" if row[name] is None else f"{row[name]:,.8f}".rstrip("0").rstrip(".") for name in columns],
                      row["quote_time"] or "—"]
            self.quote_table.append(row["sequence"], values, scroll=self.autoscroll.get())
            self._quote_cursor = row["sequence"]

    def show_page(self, page: str):
        self._page = page
        realtime = page == "realtime"
        self.page_title.configure(text="实时数据下载" if realtime else "交易数据下载")
        self.page_subtitle.configure(text="配置采集任务，持续保存最新行情。" if realtime else "历史与交易数据下载模块。")
        self.nav_realtime.configure(fg_color="#21525A" if realtime else "transparent")
        self.nav_trading.configure(fg_color="transparent" if realtime else "#21525A")
        if realtime:
            self.trading_page.grid_remove()
            self.metrics.grid()
            self.realtime_page.grid()
        else:
            self.realtime_page.grid_remove()
            self.metrics.grid_remove()
            self.trading_page.grid(row=3, column=0, sticky="nsew")

    def form_value(self) -> dict:
        return {"symbols": self.symbols.get("1.0", "end-1c"),
                "interval": self.interval.get(), "output_dir": self.output_dir.get()}

    def set_form(self, value: dict):
        self.symbols.configure(state="normal")
        self.symbols.delete("1.0", "end")
        self.symbols.insert("1.0", "\n".join(value["symbols"]))
        self.interval.set(f"{value['interval']:g}")
        self.output_dir.set(value["output_dir"])
        self._update_symbol_count()

    def _update_symbol_count(self, _event=None):
        try:
            symbols = parse_symbols(self.symbols.get("1.0", "end-1c"))
            count = str(len(symbols))
            self.symbol_selector.configure(values=symbols or ["—"])
            if self.display_symbol.get() not in symbols:
                self.display_symbol.set(symbols[0] if symbols else "—")
                self.select_symbol()
        except ValueError:
            count = "待检查"
        self.metric_values["symbols"].configure(text=count)

    def _feedback(self, message: str, *, error=False):
        self.feedback.configure(text=message, text_color="#B94242" if error else TEAL)

    def _action_error(self, exc: Exception):
        self._feedback(str(exc), error=True)
        self.service.log("ERROR", str(exc))

    def save_config(self):
        try:
            self.set_form(self.service.save(self.form_value()))
            self._feedback("配置已保存，下次打开时自动恢复。")
        except (ValueError, OSError) as exc:
            self._action_error(exc)

    def start_collection(self):
        try:
            self.service.start(self.form_value())
            self.set_form(self.service.config())
            self._feedback("采集中；停止后可修改配置。")
            self.refresh(schedule=False)
        except (ValueError, OSError, RuntimeError) as exc:
            self._action_error(exc)

    def stop_collection(self):
        self.service.stop()
        self._feedback("正在停止，等待当前请求完成并保存。")
        self.refresh(schedule=False)

    def import_symbols(self):
        paths = filedialog.askopenfilenames(parent=self, title="导入标的文件（可多选）",
                                            filetypes=[("标的文件", "*.json *.txt *.list")])
        if not paths:
            return
        try:
            current = parse_symbols(self.symbols.get("1.0", "end-1c"))
            imported = load_symbols([Path(path) for path in paths])
            symbols = list(dict.fromkeys(current + imported))
            self.symbols.delete("1.0", "end")
            self.symbols.insert("1.0", "\n".join(symbols))
            self._update_symbol_count()
            self._feedback(f"已合并 {len(paths)} 个文件，共 {len(symbols)} 个标的。保存或开始后生效。")
        except (ValueError, OSError, UnicodeError) as exc:
            self._action_error(exc)

    def export_symbols(self):
        try:
            symbols = parse_symbols(self.symbols.get("1.0", "end-1c"))
            if not symbols:
                raise ValueError("请先填写需要导出的标的")
            path = filedialog.asksaveasfilename(parent=self, title="导出标的列表", initialfile="symbols.json",
                                              defaultextension=".json", filetypes=[("JSON 标的列表", "*.json")])
            if path:
                write_json(Path(path), symbols)
                self._feedback(f"已导出 {len(symbols)} 个标的。")
        except (ValueError, OSError) as exc:
            self._action_error(exc)

    def _output_path(self) -> Path:
        raw = self.output_dir.get().strip()
        if not raw:
            raise ValueError("请先选择数据保存目录")
        path = Path(raw).expanduser()
        return (path if path.is_absolute() else self.service.root / path).resolve()

    def choose_directory(self):
        try:
            path = self._output_path()
            while not path.is_dir() and path != path.parent:
                path = path.parent
            selected = filedialog.askdirectory(parent=self, title="选择数据保存文件夹", initialdir=str(path))
            if selected:
                self.output_dir.set(selected)
        except (ValueError, OSError) as exc:
            self._action_error(exc)

    def open_output(self):
        try:
            path = self._output_path()
            if not path.is_dir():
                raise ValueError("目录尚未创建；首次开始采集时会自动创建。")
            if sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])
        except (ValueError, OSError) as exc:
            self._action_error(exc)

    def clear_logs(self):
        self._cursor = self.service.snapshot()["log_cursor"]
        self.status_table.clear()
        self.status_detail.configure(text="显示记录已清空；磁盘数据保留。")

    def refresh(self, *, schedule=True):
        if schedule:
            self._poll_id = None
        state = self.service.snapshot(self._cursor)
        worker = self.service.worker
        alive = worker is not None and worker.is_alive()
        busy = state["status"] in ACTIVE_STATES or alive
        if self._closing and not alive:
            self.destroy()
            return
        if busy != self._busy:
            self._busy = busy
            for widget in self.editable:
                widget.configure(state="disabled" if busy or self._closing else "normal")
        self.start_button.configure(state="disabled" if busy or self._closing else "normal")
        self.stop_button.configure(state="normal" if state["status"] in {"starting", "running"} and not self._closing else "disabled")
        statuses = {"idle": "待启动", "starting": "启动中", "running": "采集中",
                    "stopping": "正在停止", "stopped": "已停止", "failed": "运行失败"}
        is_error = state["status"] == "failed"
        self.status_label.configure(text="●  " + statuses.get(state["status"], state["status"]),
                                    text_color="#B94242" if is_error else TEAL,
                                    fg_color="#FCECED" if is_error else "#E5F2EF")
        stats = state["stats"]
        self.metric_values["polls"].configure(text=str(stats["polls"]))
        self.metric_values["batches"].configure(text=str(stats["batches"]))
        latency = stats["last_latency_ms"]
        self.metric_values["latency"].configure(text="—" if latency is None else f"{latency} ms")
        self.result_label.configure(text=f"成功 {stats['successful']}  /  异常 {stats['unsuccessful']}")
        self.response_label.configure(text="最近响应  " + clock_text(stats["last_response_at"]))
        if state["run_id"] != self._quote_run:
            self._quote_run = state["run_id"]
            self._quote_cursor = 0
            self.quote_table.clear()
        self._refresh_quotes()
        if state["error"] and state["error"] != self._last_error:
            self._feedback(state["error"], error=True)
        elif not busy and state["status"] == "stopped":
            if self.feedback.cget("text") in ("正在停止，等待当前请求完成并保存。", "采集中；停止后可修改配置。"):
                self._feedback("采集已结束，数据已保存。可修改配置后重新开始。")
        self._last_error = state["error"]
        labels = {"success": "成功", "partial": "部分失败", "failed": "失败", "info": "信息", "warning": "提示"}
        for row in state["reports"]:
            self.status_table.append(row["id"], [clock_text(row["timestamp"]), labels.get(row["status"], row["status"]),
                row["description"], ", ".join(row["failed_symbols"]) or "—"], row["status"], scroll=self.autoscroll.get())
        self._cursor = state["log_cursor"]
        if schedule:
            self._poll_id = self.after(250, self.refresh)

    def request_close(self):
        self._closing = True
        self.service.stop()
        self.show_page("realtime")
        self.title("Delta1 · 正在保存并退出…")
        self._feedback("正在保存并退出，等待当前请求结束…")
        self.footer.configure(text="窗口将在当前请求完成或超时、数据保存后自动关闭。")
        self.refresh(schedule=False)

    def report_callback_exception(self, exc_type, exc_value, traceback):
        logging.getLogger(__name__).error("Desktop callback failed", exc_info=(exc_type, exc_value, traceback))
        self._action_error(exc_value)

    def destroy(self):
        self.update_idletasks()
        # CustomTkinter also schedules widget and DPI callbacks on this Tcl
        # interpreter. Cancel timers before deleting their widget commands.
        for callback in self.tk.splitlist(self.tk.call("after", "info")):
            self.tk.call("after", "cancel", callback)
        self._poll_id = None
        super().destroy()
