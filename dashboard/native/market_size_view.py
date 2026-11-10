"""Two dated size pies. Partial totals are explicitly qualified."""
from PySide6.QtCore import Qt,QRectF
from PySide6.QtGui import QColor,QPainter,QFont
from PySide6.QtWidgets import QWidget
from .theme import ACCENT,BORDER,CHART_COLORS,MUTED,PANEL,TEXT


class SizePie(QWidget):
    def __init__(self):
        super().__init__();self.data={};self.setMinimumHeight(280);self.setMinimumWidth(0)

    def render(self,data):
        self.data=data or {};self.setToolTip((self.data.get('source') or '')+'\n'+str(self.data.get('as_of') or '')+'\n'+str(self.data.get('reason') or ''))
        self.update()

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rows=self.data.get('rows',[]);total=self.data.get('known_total_cny')
        if total is None:
            p.setPen(QColor(MUTED));p.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,self.data.get('reason') or '等待真实规模数据');return
        diameter=min(240,self.height()-24,max(140,self.width()*.40));left=QRectF(4,(self.height()-diameter)/2,diameter,diameter)
        angle=90*16
        for i,row in enumerate(rows):
            part=round(360*16*row.get('share_pct',0)/100)
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(CHART_COLORS[i%len(CHART_COLORS)]));p.drawPie(left,angle,-part);angle-=part
        if not total:p.setPen(QColor(BORDER));p.setBrush(QColor(PANEL));p.drawEllipse(left)
        inner=left.adjusted(diameter*.21,diameter*.21,-diameter*.21,-diameter*.21)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(PANEL));p.drawEllipse(inner)
        font=QFont(p.font());font.setPixelSize(27);font.setBold(True);p.setFont(font);p.setPen(QColor(ACCENT))
        p.drawText(inner,Qt.AlignmentFlag.AlignCenter,f'{total/1e8:,.1f}\n亿元')
        start=diameter+24;available=max(40,self.width()-start-6);height=min(61,(self.height()-12)/max(1,len(rows)))
        top=(self.height()-height*len(rows))/2
        for i,row in enumerate(rows):
            y=top+i*height;color=QColor(CHART_COLORS[i%len(CHART_COLORS)])
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(color);p.drawRoundedRect(QRectF(start,y+7,10,10),2,2)
            font.setPixelSize(17);font.setBold(False);p.setFont(font);p.setPen(QColor(TEXT))
            name=p.fontMetrics().elidedText(row.get('name') or row.get('symbol',''),Qt.TextElideMode.ElideRight,int(available-20))
            p.drawText(QRectF(start+18,y,available-18,24),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,name)
            font.setPixelSize(24);font.setBold(True);p.setFont(font);p.setPen(color)
            p.drawText(QRectF(start+18,y+23,available-18,31),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,
                f"{row['amount_cny']/1e8:,.1f}亿  ·  {row.get('share_pct',0):.1f}%")
