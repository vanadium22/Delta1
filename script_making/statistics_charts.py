"""One pnl1 history chart, embedded in the existing statistics page and attachment."""
from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen

NAVY, LINE, POSITIVE, NEGATIVE = "#18334f", "#3b59b8", "#cf5b55", "#159588"


def limits(values):
    if not values:
        return -1., 1.
    lo, hi = min(0., min(values)), max(0., max(values))
    span = hi - lo
    return (lo - span * .12, hi + span * .12) if span else (-1., 1.)


def chart_image(snapshot, width=1600, height=780):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("#f3f6fb"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(width / 1600, height / 780)

    def text(x, y, w, h, value, size=12, color=NAVY, bold=False, align=Qt.AlignmentFlag.AlignLeft):
        painter.setFont(QFont("Microsoft YaHei UI", size, QFont.Weight.Bold if bold else QFont.Weight.Normal))
        painter.setPen(QColor(color))
        painter.drawText(QRectF(x, y, w, h), align | Qt.AlignmentFlag.AlignVCenter, value)

    history = snapshot.get("history", {}).get("pnl", {})
    points = history.get("points", [])
    text(40, 22, 1480, 44, "pnl1 · 境内权益互换台收益", 24, bold=True)
    text(40, 76, 1480, 30, f"{history.get('year', '')}年 · 年初至 {history.get('through') or '未选择'} · 当年全部已取得报表 · 金额单位：万元", 12)
    text(40, 110, 1480, 30, "横轴为报表日期。原表取 T-2 数据；柱形为相邻报表差额，缺日报时代表区间变动。", 12, "#64788e")
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("white"))
    painter.drawRoundedRect(QRectF(30, 160, 1540, 492), 14, 14)
    text(60, 177, 680, 32, "━━ 累计净利润 · 左轴", 13, LINE)
    text(840, 177, 700, 32, "■ 相邻两期净利润变动 · 右轴（红正 / 绿负）", 13, "#a4514e")
    plot = QRectF(145, 236, 1300, 320)
    totals = [None if point["current"] is None else float(point["current"]) / 10000 for point in points]
    changes = [None if point["change"] is None else float(point["change"]) / 10000 for point in points]
    available = [value for value in totals if value is not None]
    if not available:
        text(plot.left(), plot.top(), plot.width(), plot.height(), "当年尚无可用 pnl1 历史数据。", 18, "#64788e", align=Qt.AlignmentFlag.AlignCenter)
    else:
        left_lo, left_hi = limits(available)
        right_lo, right_hi = limits([value for value in changes if value is not None])

        def y(value, lo, hi):
            return plot.bottom() - (value - lo) / (hi - lo) * plot.height()

        def x(index):
            return plot.left() + (index + .5) / len(points) * plot.width()

        for tick in range(5):
            ratio = tick / 4
            pos = plot.bottom() - ratio * plot.height()
            painter.setPen(QPen(QColor("#e3e9f1"), 1))
            painter.drawLine(QPointF(plot.left(), pos), QPointF(plot.right(), pos))
            for value, left, color in ((left_lo + ratio * (left_hi-left_lo), 35, LINE),
                                       (right_lo + ratio * (right_hi-right_lo), plot.right()+10, "#a4514e")):
                text(left, pos-12, 100, 25, f"{0 if abs(value) < .05 else value:,.1f}", 11, color,
                     align=Qt.AlignmentFlag.AlignRight if left == 35 else Qt.AlignmentFlag.AlignLeft)
        zero = y(0, right_lo, right_hi)
        painter.setPen(QPen(QColor("#c7d3e2"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(plot.left(), zero), QPointF(plot.right(), zero))
        bar_width = min(28., plot.width() / len(points) * .55)
        for index, amount in enumerate(changes):
            if amount is None:
                continue
            pos = y(amount, right_lo, right_hi)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(POSITIVE if amount >= 0 else NEGATIVE))
            painter.drawRoundedRect(QRectF(x(index)-bar_width/2, min(pos, zero), bar_width, max(1., abs(pos-zero))), 2, 2)
        path, connected = QPainterPath(), False
        for index, amount in enumerate(totals):
            if amount is None:
                connected = False
                continue
            point = QPointF(x(index), y(amount, left_lo, left_hi))
            if connected:
                path.lineTo(point)
            else:
                path.moveTo(point)
            connected = True
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(LINE), 3))
        painter.drawPath(path)
        painter.setBrush(QColor("white"))
        for index, amount in enumerate(totals):
            if amount is not None and len(points) <= 60:
                painter.drawEllipse(QPointF(x(index), y(amount, left_lo, left_hi)), 4, 4)
        ticks = sorted({round(i * (len(points)-1) / max(1, min(7, len(points)-1))) for i in range(min(8, len(points)))})
        for index in ticks:
            text(x(index)-58, plot.bottom()+12, 116, 28, points[index]["date"][5:], 11, "#64788e", align=Qt.AlignmentFlag.AlignCenter)
    text(60, 604, 1480, 30, f"已读取 {len(points)} 份历史报表，{len(available)} 份有效；首份或前一份解析失败时不画差额柱，不补零、不跨年相减。", 11, "#64788e")
    text(40, 674, 1480, 30, "历史差额始终按相邻报表计算；上方三值卡片使用所选的本期和上期日期。", 11, "#64788e")
    error_count = len(history.get("errors", {}))
    text(40, 717, 1480, 30, f"{error_count} 份解析失败，详见统计记录。" if error_count else "来源：盈亏统计 / 累积盈亏统计 / 境内权益互换台 / 净利润", 11, "#a4514e" if error_count else "#64788e")
    painter.end()
    return image


def chart_html(snapshot):
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    chart_image(snapshot).save(buffer, "PNG")
    encoded = bytes(buffer.data().toBase64()).decode("ascii")
    return f'<p style="line-height:100%;"><img src="data:image/png;base64,{encoded}" width="1500" height="731" alt="pnl1 当年累计报表收益图" /></p>'
