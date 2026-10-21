"""Native, dependency-free dual-axis charts rendered from frozen annual data."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QScrollArea

from .statistics import GROUPS
from .storage import ReportError

LABELS = {"swap": "收益互换日报", "strategy": "D1策略台日报"}
NAVY, LINE, POSITIVE, NEGATIVE = "#18334f", "#3b59b8", "#cf5b55", "#159588"


def limits(values):
    if not values:
        return -1., 1.
    lo, hi = min(0., min(values)), max(0., max(values))
    span = hi - lo
    if not span:
        return -1., 1.
    return lo - span * .12, hi + span * .12


def chart_image(snapshot, kind, width=1600, height=1120):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("#f3f6fb"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(width / 1600, height / 1120)

    def text(x, y, w, h, value, size=12, color=NAVY, bold=False, align=Qt.AlignmentFlag.AlignLeft):
        painter.setFont(QFont("Microsoft YaHei UI", size, QFont.Weight.Bold if bold else QFont.Weight.Normal))
        painter.setPen(QColor(color))
        painter.drawText(QRectF(x, y, w, h), align | Qt.AlignmentFlag.AlignVCenter, value)

    history = snapshot.get("history", {}).get(kind, {})
    points = history.get("points", [])
    text(40, 22, 1200, 30, "DELTA ONE  /  日报年度观察", 11, "#64788e")
    text(40, 60, 1400, 52, LABELS[kind] + " · 总盈亏与当日盈亏", 25, bold=True)
    config = snapshot["config"]
    text(40, 118, 1480, 32, f"{history.get('year', '')}年本地日报  ·  截止 {history.get('through') or '未选择'}  ·  "
         f"|{config['metric']}| ≥ {float(config['threshold']):,.2f}  ·  剔除名单按本次设置", 11)
    text(40, 151, 1480, 26, "每日报表分别筛选观察标的；组成可能变化。各来源独立，不代表全台盈亏。金额轴单位：万元。", 11, "#64788e")
    for group_index, group in enumerate(GROUPS):
        card = QRectF(30, 198 + group_index * 410, 1540, 392)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("white"))
        painter.drawRoundedRect(card, 14, 14)
        top = card.top()
        text(54, top + 12, 750, 30, group, 16, bold=True)
        text(870, top + 12, 270, 30, "━━ 总盈亏 · 左轴", 11, LINE)
        text(1150, top + 12, 370, 30, "■ 当日盈亏 · 右轴（红正 / 绿负）", 11, "#a4514e")
        plot = QRectF(140, top + 67, 1310, 248)
        series = []
        for point in points:
            data = point.get("groups")
            series.append((float(data[group_index]["total"]) / 10000,
                           float(data[group_index]["daily"]) / 10000) if data else None)
        values = [value for value in series if value is not None]
        if not values:
            text(plot.left(), plot.top(), plot.width(), plot.height(), "今年尚无可用历史统计；缺失值不按零绘制。", 16,
                 "#64788e", align=Qt.AlignmentFlag.AlignCenter)
            continue
        left_lo, left_hi = limits([value[0] for value in values])
        right_lo, right_hi = limits([value[1] for value in values])

        def y(value, lo, hi):
            return plot.bottom() - (value - lo) / (hi - lo) * plot.height()

        def x(index):
            return plot.left() + (index + .5) / len(points) * plot.width()

        for tick in range(5):
            ratio = tick / 4
            pos = plot.bottom() - ratio * plot.height()
            painter.setPen(QPen(QColor("#e3e9f1"), 1))
            painter.drawLine(QPointF(plot.left(), pos), QPointF(plot.right(), pos))
            left_value, right_value = left_lo + ratio * (left_hi-left_lo), right_lo + ratio * (right_hi-right_lo)
            text(35, pos - 12, 94, 25, f"{0 if abs(left_value) < .05 else left_value:,.1f}", 10, LINE,
                 align=Qt.AlignmentFlag.AlignRight)
            text(plot.right() + 10, pos - 12, 105, 25, f"{0 if abs(right_value) < .05 else right_value:,.1f}", 10, "#a4514e")
        zero = y(0, right_lo, right_hi)
        painter.setPen(QPen(QColor("#c7d3e2"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(plot.left(), zero), QPointF(plot.right(), zero))
        bar_width = max(1.5, min(24., plot.width() / len(points) * .55))
        for index, value in enumerate(series):
            if value is None:
                continue
            amount = value[1]
            pos = y(amount, right_lo, right_hi)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(POSITIVE if amount >= 0 else NEGATIVE))
            painter.drawRoundedRect(QRectF(x(index) - bar_width / 2, min(pos, zero), bar_width,
                                          max(1., abs(pos - zero))), 2, 2)
        path, connected = QPainterPath(), False
        for index, value in enumerate(series):
            if value is None:
                connected = False
                continue
            point = QPointF(x(index), y(value[0], left_lo, left_hi))
            if connected:
                path.lineTo(point)
            else:
                path.moveTo(point)
            connected = True
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(LINE), 3))
        painter.drawPath(path)
        if len(points) <= 35:
            painter.setBrush(QColor("white"))
            for index, value in enumerate(series):
                if value is not None:
                    painter.drawEllipse(QPointF(x(index), y(value[0], left_lo, left_hi)), 3.5, 3.5)
        ticks = sorted({round(i * (len(points) - 1) / max(1, min(7, len(points) - 1)))
                        for i in range(min(8, len(points)))})
        for index in ticks:
            text(x(index) - 58, plot.bottom() + 7, 116, 24, points[index]["date"][5:], 10, "#64788e",
                 align=Qt.AlignmentFlag.AlignCenter)
        text(140, top + 351, 1310, 25, f"报表日期 · {len(points)} 份本地文件；{len(values)} 份可用。无文件日期不补点，解析失败日期断开折线。", 10, "#64788e")
    errors = history.get("errors", {})
    text(40, 1030, 1480, 30, ("未绘制日期：" + "、".join(errors)) if errors else "历史数据与当前统计共用来源哈希、阈值和剔除规则。", 10, "#8b5c2d" if errors else "#64788e")
    text(40, 1070, 1480, 26, f"生成：{snapshot['created_at']}  ·  记录 {snapshot['id'][:10]}", 10, "#64788e")
    painter.end()
    return image


def save_chart(snapshot, kind, path):
    if not chart_image(snapshot, kind).save(str(path), "PNG"):
        raise ReportError("历史图保存失败，请检查目标目录。")


class ChartView(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = None
        self.canvas = QLabel()
        self.setWidget(self.canvas)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def set_image(self, image):
        self.image = image
        self.refresh_image()

    def refresh_image(self):
        if self.image is not None:
            scaled = self.image.scaledToWidth(max(1, self.width() - 24), Qt.TransformationMode.SmoothTransformation)
            self.canvas.setPixmap(QPixmap.fromImage(scaled))
            self.canvas.resize(scaled.size())
        else:
            self.canvas.clear()
            self.canvas.resize(1, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh_image()
