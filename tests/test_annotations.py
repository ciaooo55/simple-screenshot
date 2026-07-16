from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainterPath

from simple_screenshot.annotations import PenAnnotation, TextAnnotation, render_selection


def test_render_selection_crops_expected_area():
    desktop = QImage(100, 80, QImage.Format.Format_ARGB32)
    desktop.fill(QColor("white"))

    result = render_selection(desktop, QRectF(10, 20, 40, 30), 1.0, [])

    assert result.width() == 40
    assert result.height() == 30
    assert QColor(result.pixel(0, 0)) == QColor("white")


def test_pen_annotation_is_composited_relative_to_selection():
    desktop = QImage(100, 80, QImage.Format.Format_ARGB32)
    desktop.fill(QColor("white"))
    path = QPainterPath(QPointF(15, 25))
    path.lineTo(QPointF(30, 25))

    result = render_selection(
        desktop,
        QRectF(10, 20, 40, 30),
        1.0,
        [PenAnnotation(path, "#ff0000", 4.0)],
    )

    pixel = QColor(result.pixel(10, 5))
    assert pixel.red() > 220
    assert pixel.green() < 80
    assert pixel.blue() < 80


def test_high_dpi_selection_uses_render_scale():
    desktop = QImage(200, 160, QImage.Format.Format_ARGB32)
    desktop.fill(QColor("white"))

    result = render_selection(desktop, QRectF(10, 20, 40, 30), 2.0, [])

    assert result.width() == 80
    assert result.height() == 60


def test_text_annotation_is_rendered():
    desktop = QImage(240, 140, QImage.Format.Format_ARGB32)
    desktop.fill(QColor("white"))

    result = render_selection(
        desktop,
        QRectF(0, 0, 200, 100),
        1.0,
        [TextAnnotation(QPointF(10, 10), "中文 test", "#ff0000", 24, 170)],
    )

    non_white = 0
    for y in range(8, 50):
        for x in range(8, 180):
            if QColor(result.pixel(x, y)) != QColor("white"):
                non_white += 1
    assert non_white > 20
