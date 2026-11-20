"""Export account performance charts as PNG using the company Qt runtime."""

from collections import defaultdict
import math
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

COLORS = {"2602": "#2563B5", "5526": "#148579", "5524": "#BC652A", "合计": "#27374D"}
CHART_VERSION = 2
ACCOUNT_NOTES = ("单日及累计盈亏已扣流水手续费。权益与资金明细齐全时采用结算权益差。",
                 "曲线断点表示该交易日缺少必要数据。逐日口径、费用和完整度见 Excel。")


def chart_font():
    from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics

    windows_fonts = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Fonts"
    families = []
    for filename in ("msyh.ttc", "simhei.ttf", "simsun.ttc"):
        path = windows_fonts / filename
        if path.is_file():
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id >= 0:
                families.extend(QFontDatabase.applicationFontFamilies(font_id))
    for family in dict.fromkeys([*families, "Microsoft YaHei", "Noto Sans CJK SC", "SimHei"]):
        metrics = QFontMetrics(QFont(family))
        if all(metrics.inFont(char) for char in "账户012"):
            return family
    raise RuntimeError("收益图片需要可用的中文字体（例如微软雅黑）。")


def write_charts(paths, history, annual):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication([])
    family = chart_font()
    for path, timeline, title, key in (
        (paths[0], history, "历史至今 · 账户收益", "history_pnl"),
        (paths[1], annual, f"{annual[-1]['day'][:4]}年 · 账户收益", "ytd_pnl"),
    ):
        write_chart(path, timeline, title, key, family)
    # Hold the Qt application while fonts and images are in use.
    del app


def write_strategy_chart(path, timeline, summary):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication([])
    colors = {"Excel股指期货": "#2563B5", "5526实盘净盈亏": "#148579"}
    notes = ("Excel 日度和年内累计使用同口径日报余额差。5526 使用账户净盈亏。",
             "曲线断点及汇总中的「—」表示缺数据。来源、日期和口径详见对账 Excel。")
    write_chart(path, timeline, "策略台 PnL 对账", "ytd_pnl", chart_font(),
                palette=colors, summary=summary, notes=notes)
    del app


def write_chart(path, timeline, title, cumulative_key, family, *, palette=COLORS, summary=(), notes=ACCOUNT_NOTES):
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen

    series = defaultdict(list)
    days = list(dict.fromkeys(row["day"] for row in timeline))
    for row in timeline:
        series[row["account"]].append(row)

    image = QImage(1600 if summary else 1440, 1010, QImage.Format.Format_RGB32)
    panel_end = 916 if summary else 1394
    image.fill(QColor("#F3F6FA"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    def text(x, y, label, *, size=16, color="#25354A", bold=False, align_right=False):
        font = QFont(family)
        font.setPixelSize(size)
        font.setBold(bold)
        painter.setFont(font)
        painter.setPen(QColor(color))
        if align_right:
            x -= QFontMetricsF(font).horizontalAdvance(label)
        painter.drawText(QPointF(x, y), label)

    def panel(top, label, metric):
        painter.fillRect(QRectF(46, top, panel_end - 46, 361), QColor("#FFFFFF"))
        text(70, top + 37, label, size=23, bold=True)
        text(70, top + 69, "金额 · 万元", color="#5C6C80")
        left, right, first_y, last_y = 150, panel_end - 40, top + 90, top + 303
        by_account = {account: [float(row[metric]) / 10000 if row[metric] is not None else None
                               for row in series[account]] for account in palette}
        known = [value for points in by_account.values() for value in points if value is not None]
        floor, ceiling = min([0, *known]), max([0, *known])
        spread = ceiling - floor or 1
        raw_step = spread / 4
        power = 10 ** math.floor(math.log10(raw_step))
        step = min(value * power for value in (1, 2, 2.5, 5, 10) if value * power >= raw_step)
        floor = math.floor(floor / step) * step
        ceiling = math.ceil(ceiling / step) * step
        if floor == ceiling:
            floor, ceiling = -step, step

        def x_at(index):
            return (left + right) / 2 if len(days) == 1 else left + (right - left) * index / (len(days) - 1)

        def y_at(value):
            return last_y - (last_y - first_y) * (value - floor) / (ceiling - floor)

        for index in range(round((ceiling - floor) / step) + 1):
            value = floor + index * step
            y = y_at(value)
            painter.setPen(QPen(QColor("#AAB8C9" if abs(value) < step / 100 else "#E0E7EF"), 1))
            painter.drawLine(QPointF(left, y), QPointF(right, y))
            digits = max(0, min(6, -math.floor(math.log10(step)) + (step / power == 2.5)))
            text(68, y + 5, f"{0 if abs(value) < step / 100 else value:,.{digits}f}", size=15, color="#5C6C80")
        ticks = 1 if len(days) == 1 else min(7, len(days))
        for step_index in range(ticks):
            index = 0 if ticks == 1 else round((len(days) - 1) * step_index / (ticks - 1))
            label = days[index][2:] if days[0][:4] != days[-1][:4] else days[index][5:]
            text(x_at(index) - 32, last_y + 29, label, size=15, color="#5C6C80")
        for account, points in by_account.items():
            color = QColor(palette[account])
            width = 3.0 if account == "合计" else 2.0
            painter.setPen(QPen(color, width, Qt.PenStyle.DashLine if account == "合计" else Qt.PenStyle.SolidLine))
            painter.setBrush(color)
            previous = None
            for index, value in enumerate(points):
                point = None if value is None else QPointF(x_at(index), y_at(value))
                if point is not None:
                    if previous is not None:
                        painter.drawLine(previous, point)
                    painter.drawEllipse(point, 2.5 if account == "合计" else 2.0, 2.5 if account == "合计" else 2.0)
                previous = point
        if not known:
            text((290 if summary else 574), top + 192,
                 "该期间缺少可用对账数据" if summary else "该期间待补行情或权益数据", size=23, color="#5C6C80")

    def summary_table():
        painter.fillRect(QRectF(936, 152, 618, 742), QColor("#FFFFFF"))
        text(965, 189, f"{days[-1]} PnL 汇总", size=23, bold=True)
        text(965, 221, "金额 · 万元", color="#5C6C80")
        text(1380, 272, "当日", bold=True, align_right=True)
        text(1526, 272, "年内累计", bold=True, align_right=True)
        for index, (label, daily, ytd) in enumerate(summary):
            y = 323 + index * 57
            bold = index in (1, 6, 7, 8)
            if index in (0, 4, 7, 8):
                painter.setPen(QPen(QColor("#E0E7EF"), 1))
                painter.drawLine(QPointF(965, y - 33), QPointF(1526, y - 33))
            text(965, y, label, size=19, bold=bold)
            for x, value in ((1380, daily), (1526, ytd)):
                text(x, y, "—" if value is None else f"{value / 10000:,.2f}",
                     size=19, bold=bold, align_right=True)

    try:
        text(47, 76, title, size=38, bold=True)
        text(48, 117, f"{days[0]} 至 {days[-1]}  |  {len(days)} 个交易日", size=18, color="#50637C")
        for index, (account, color) in enumerate(palette.items()):
            left = 850 + index * (252 if summary else 133)
            painter.setPen(QPen(QColor(color), 4, Qt.PenStyle.DashLine if account == "合计" else Qt.PenStyle.SolidLine))
            painter.drawLine(QPointF(left, 108), QPointF(left + 27, 108))
            text(left + 36, 114, account, size=17, bold=True)
        panel(152, "单日净盈亏", "pnl")
        panel(533, "年内累计净盈亏" if summary else "累计净盈亏", cumulative_key)
        if summary:
            summary_table()
        for index, note in enumerate(notes):
            text(48, 945 + index * 32, note, size=17, color="#50637C")
    finally:
        painter.end()
    with NamedTemporaryFile(dir=path.parent, suffix=".png", delete=False) as temporary:
        stage = Path(temporary.name)
    try:
        if not image.save(str(stage), "PNG"):
            raise OSError(f"无法保存收益图：{path}")
        stage.replace(path)
    finally:
        stage.unlink(missing_ok=True)
