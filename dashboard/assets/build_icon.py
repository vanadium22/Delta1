"""Render the editable SVG to PNG and a multi-resolution Windows ICO with Qt."""
from pathlib import Path
import os
import struct
import sys

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from dashboard.native.bootstrap import configure_qt

configure_qt()
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def build(name='delta1'):
    app = QGuiApplication.instance() or QGuiApplication([])
    root = Path(__file__).resolve().parent
    svg = QSvgRenderer(str(root / (name+".svg")))
    if not svg.isValid():
        raise ValueError("Invalid icon SVG")
    images = []
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        bitmap = QImage(size, size, QImage.Format.Format_ARGB32)
        bitmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(bitmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        svg.render(painter)
        painter.end()
        encoded = QByteArray()
        buffer = QBuffer(encoded)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not bitmap.save(buffer, "PNG"):
            raise RuntimeError("PNG encoding failed")
        buffer.close()
        if size == 512:
            (root / (name+".png")).write_bytes(bytes(encoded))
        else:
            images.append((size, bytes(encoded)))
    offset = 6 + 16 * len(images)
    entries, payload = [], []
    for size, png in images:
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset))
        payload.append(png)
        offset += len(png)
    (root / (name+".ico")).write_bytes(struct.pack("<HHH", 0, 1, len(images)) + b"".join(entries + payload))
    print(f"Created {name}.ico and {name}.png")


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--name',default='delta1',choices=['delta1','research'])
    build(parser.parse_args().name)
