from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainterPath

from simple_screenshot.annotations import (
    ArrowAnnotation,
    MosaicAnnotation,
    NumberAnnotation,
    PenAnnotation,
    ShapeAnnotation,
    TextAnnotation,
    render_selection,
    translated_annotations,
)


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


def test_rect_shape_annotation_draws_border():
    desktop = QImage(100, 80, QImage.Format.Format_ARGB32)
    desktop.fill(QColor("white"))

    result = render_selection(
        desktop,
        QRectF(0, 0, 100, 80),
        1.0,
        [ShapeAnnotation(QRectF(20, 20, 40, 30), "#ff0000", 4.0, "rect")],
    )

    border_pixel = QColor(result.pixel(40, 20))
    center_pixel = QColor(result.pixel(40, 35))
    assert border_pixel.red() > 200
    assert border_pixel.green() < 90
    assert center_pixel == QColor("white")


def test_ellipse_shape_annotation_draws_curve():
    desktop = QImage(100, 80, QImage.Format.Format_ARGB32)
    desktop.fill(QColor("white"))

    result = render_selection(
        desktop,
        QRectF(0, 0, 100, 80),
        1.0,
        [ShapeAnnotation(QRectF(20, 20, 40, 30), "#ff0000", 4.0, "ellipse")],
    )

    top_middle = QColor(result.pixel(40, 20))
    corner = QColor(result.pixel(21, 21))
    assert top_middle.red() > 200
    assert corner == QColor("white")


def test_arrow_annotation_draws_line_and_head():
    desktop = QImage(120, 80, QImage.Format.Format_ARGB32)
    desktop.fill(QColor("white"))

    result = render_selection(
        desktop,
        QRectF(0, 0, 120, 80),
        1.0,
        [ArrowAnnotation(QPointF(10, 40), QPointF(100, 40), "#ff0000", 4.0)],
    )

    shaft = QColor(result.pixel(40, 40))
    head = QColor(result.pixel(96, 40))
    assert shaft.red() > 200 and shaft.green() < 90
    assert head.red() > 200 and head.green() < 90


def test_mosaic_annotation_pixelates_region():
    desktop = QImage(64, 64, QImage.Format.Format_ARGB32)
    for y in range(64):
        for x in range(64):
            color = QColor("black") if x % 2 == 0 else QColor("white")
            desktop.setPixelColor(x, y, color)

    result = render_selection(
        desktop,
        QRectF(0, 0, 64, 64),
        1.0,
        [MosaicAnnotation(QRectF(0, 0, 64, 64))],
    )

    # 马赛克块内颜色应当一致；原图相邻列黑白交替。
    first = QColor(result.pixel(0, 10))
    second = QColor(result.pixel(1, 10))
    third = QColor(result.pixel(2, 10))
    assert first == second == third


def test_number_annotation_draws_badge():
    desktop = QImage(100, 80, QImage.Format.Format_ARGB32)
    desktop.fill(QColor("white"))

    result = render_selection(
        desktop,
        QRectF(0, 0, 100, 80),
        1.0,
        [NumberAnnotation(QPointF(50, 40), 3, "#ff3b30")],
    )

    badge = QColor(result.pixel(44, 40))
    outside = QColor(result.pixel(20, 20))
    assert badge.red() > 180
    assert outside == QColor("white")


def test_short_arrow_keeps_a_visible_shaft():
    from simple_screenshot.annotations import _arrow_geometry

    arrow = ArrowAnnotation(QPointF(10, 10), QPointF(22, 10), "#ff0000", 4.0)
    geometry = _arrow_geometry(arrow)
    assert geometry is not None
    base, _head = geometry

    shaft_length = math.hypot(
        base.x() - arrow.start.x(), base.y() - arrow.start.y()
    )
    assert shaft_length >= 3.0


def test_number_badge_uses_dark_text_on_yellow():
    from simple_screenshot.annotations import _luminance

    # 黄色按感知亮度是浅色底,应配深色数字;HSL lightness 会判错。
    assert _luminance(QColor("#ffd60a")) > 150
    assert _luminance(QColor("#ff3b30")) < 150
    assert _luminance(QColor("#111111")) < 150


def test_mosaic_respects_custom_block_size():
    desktop = QImage(64, 64, QImage.Format.Format_ARGB32)
    for y in range(64):
        for x in range(64):
            color = QColor("black") if x % 2 == 0 else QColor("white")
            desktop.setPixelColor(x, y, color)

    result = render_selection(
        desktop,
        QRectF(0, 0, 64, 64),
        1.0,
        [MosaicAnnotation(QRectF(0, 0, 64, 64), block_size=16.0)],
    )

    # 16px 的块:前 16 列颜色一致。
    colors = {result.pixel(x, 8) for x in range(0, 16)}
    assert len(colors) == 1


def test_translated_annotations_cover_all_types():
    path = QPainterPath(QPointF(1, 1))
    path.lineTo(QPointF(2, 2))
    annotations = [
        PenAnnotation(path, "#ff0000", 2.0),
        TextAnnotation(QPointF(5, 5), "hi", "#ff0000", 16, 100.0),
        ArrowAnnotation(QPointF(1, 2), QPointF(3, 4), "#ff0000", 2.0),
        ShapeAnnotation(QRectF(1, 1, 4, 4), "#ff0000", 2.0, "rect"),
        MosaicAnnotation(QRectF(2, 2, 6, 6)),
        NumberAnnotation(QPointF(7, 8), 1, "#ff0000"),
    ]

    moved = translated_annotations(annotations, 10, 20)

    assert moved[0].path.elementAt(0).x == 11
    assert moved[1].position == QPointF(15, 25)
    assert moved[2].start == QPointF(11, 22)
    assert moved[2].end == QPointF(13, 24)
    assert moved[3].rect == QRectF(11, 21, 4, 4)
    assert moved[4].rect == QRectF(12, 22, 6, 6)
    assert moved[5].center == QPointF(17, 28)
