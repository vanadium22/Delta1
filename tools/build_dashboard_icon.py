"""Rebuild the tracked multi-resolution ICO from its vector source, offscreen."""
import io
import os
from pathlib import Path


def main():
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from dashboard.native.bootstrap import configure_qt
    configure_qt()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtGui import QImage,QPainter
    from PySide6.QtCore import Qt,QBuffer,QIODevice
    from PIL import Image
    app=QApplication.instance() or QApplication([])
    root=Path(__file__).resolve().parents[1]/'dashboard/assets'
    renderer=QSvgRenderer(str(root/'company_overview.svg'))
    if not renderer.isValid():raise ValueError('invalid SVG')
    image=QImage(256,256,QImage.Format.Format_ARGB32);image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image);renderer.render(painter);painter.end()
    buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly);image.save(buffer,'PNG')
    with Image.open(io.BytesIO(bytes(buffer.data()))) as bitmap:
        bitmap.save(root/'company_overview.ico',format='ICO',sizes=[(s,s) for s in (16,24,32,48,64,128,256)])
    print(str(root/'company_overview.ico'))
    return 0


if __name__=='__main__':raise SystemExit(main())
