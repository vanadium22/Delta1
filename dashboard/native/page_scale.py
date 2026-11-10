"""Scale complete card pages without changing numerical or source data."""
from PySide6.QtCore import QEvent, QRectF, Qt, QTimer
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView


class ScaleScrollArea(QGraphicsView):
    """Medium fits the full page; large keeps native size and scrolling."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode='medium';self.body=None;self.proxy=None;self._queued=False;self._adjusting=False
        self.setScene(QGraphicsScene(self));self.setAlignment(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignTop)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().installEventFilter(self)
        self.setRenderHints(self.renderHints())

    def setWidgetResizable(self, value):
        pass  # The logical body is resized explicitly before the transform.

    def setWidget(self, widget):
        # A proxy's QWidget has no QWidget ancestor, so give it the same theme
        # explicitly instead of relying on the main window's style inheritance.
        from .card_style import CARD_STYLE
        widget.setStyleSheet(CARD_STYLE)
        self.body=widget;self.proxy=self.scene().addWidget(widget);widget.installEventFilter(self);self.request_fit()

    def widget(self):
        return self.body

    def set_page_scale(self, mode):
        self.mode=mode if mode in ('large','medium','small') else 'medium';self.request_fit()

    def resizeEvent(self, event):
        super().resizeEvent(event);self.request_fit()

    def showEvent(self, event):
        super().showEvent(event);self.request_fit()

    def eventFilter(self, obj, event):
        if obj is self.viewport() and event.type()==QEvent.Type.Resize:self.request_fit()
        if obj is self.body and event.type() in (QEvent.Type.LayoutRequest,QEvent.Type.Show):self.request_fit()
        return super().eventFilter(obj,event)

    def request_fit(self):
        if self._queued or self._adjusting or not self.isVisible():return
        self._queued=True;QTimer.singleShot(0,self.fit_page)

    def fit_page(self):
        self._queued=False
        if self.body is None or self._adjusting or not self.isVisible():return
        self._adjusting=True
        try:
            width=max(1,self.viewport().width()-4);height=max(1,self.viewport().height()-4)
            # Keep the same responsive page; only change its display scale.
            scale=1.0;content_height=height;logical_width=width
            for _ in range(4):
                logical_width=max(width,int(width/scale),self.body.minimumSizeHint().width())
                self.body.resize(logical_width,max(1,int(content_height)))
                layout=self.body.layout()
                if layout:layout.activate()
                measured=layout.totalHeightForWidth(logical_width) if layout and layout.hasHeightForWidth() else self.body.sizeHint().height()
                content_height=max(self.body.minimumSizeHint().height(),measured,1)
                fitted=min(1.0,height/max(1,content_height))
                target=1.0 if self.mode=='large' else fitted*(.84 if self.mode=='small' else 1.0)
                # Narrow windows retain usable text and normal scrolling.
                if width<1100:target=max(.72,target)
                if self.mode!='large':target=min(target,width/max(1,logical_width))
                target=max(.35,target)
                if abs(target-scale)<.003:break
                scale=target
            logical_width=max(width,int(width/scale),self.body.minimumSizeHint().width())
            self.body.resize(logical_width,max(int(content_height),int(height/scale)))
            self.setTransform(QTransform.fromScale(scale,scale))
            self.setSceneRect(QRectF(0,0,logical_width,max(content_height,height/scale)))
            self.display_scale=scale
        finally:self._adjusting=False


def apply_scale(window, mode):
    for area in window.findChildren(ScaleScrollArea):area.set_page_scale(mode)
