from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TypeAlias

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QTextOption,
    QTransform,
)


@dataclass(slots=True)
class PenAnnotation:
    path: QPainterPath
    color: str
    width: float


@dataclass(slots=True)
class TextAnnotation:
    position: QPointF
    text: str
    color: str
    font_size: int
    width: float


@dataclass(slots=True)
class ArrowAnnotation:
    start: QPointF
    end: QPointF
    color: str
    width: float


@dataclass(slots=True)
class ShapeAnnotation:
    rect: QRectF
    color: str
    width: float
    shape: str  # "rect" | "ellipse"


@dataclass(slots=True)
class MosaicAnnotation:
    rect: QRectF
    block_size: float = 8.0


@dataclass(slots=True)
class NumberAnnotation:
    center: QPointF
    number: int
    color: str
    radius: float = 14.0


Annotation: TypeAlias = (
    PenAnnotation
    | TextAnnotation
    | ArrowAnnotation
    | ShapeAnnotation
    | MosaicAnnotation
    | NumberAnnotation
)


def translated_annotations(
    annotations: list[Annotation],
    dx: float,
    dy: float,
) -> list[Annotation]:
    transform = QTransform()
    transform.translate(dx, dy)
    translated: list[Annotation] = []
    for command in annotations:
        if isinstance(command, PenAnnotation):
            translated.append(
                PenAnnotation(
                    transform.map(command.path),
                    command.color,
                    command.width,
                )
            )
        elif isinstance(command, TextAnnotation):
            translated.append(
                TextAnnotation(
                    QPointF(command.position.x() + dx, command.position.y() + dy),
                    command.text,
                    command.color,
                    command.font_size,
                    command.width,
                )
            )
        elif isinstance(command, ArrowAnnotation):
            translated.append(
                ArrowAnnotation(
                    QPointF(command.start.x() + dx, command.start.y() + dy),
                    QPointF(command.end.x() + dx, command.end.y() + dy),
                    command.color,
                    command.width,
                )
            )
        elif isinstance(command, ShapeAnnotation):
            translated.append(
                ShapeAnnotation(
                    command.rect.translated(dx, dy),
                    command.color,
                    command.width,
                    command.shape,
                )
            )
        elif isinstance(command, MosaicAnnotation):
            translated.append(
                MosaicAnnotation(
                    command.rect.translated(dx, dy),
                    command.block_size,
                )
            )
        else:
            translated.append(
                NumberAnnotation(
                    QPointF(command.center.x() + dx, command.center.y() + dy),
                    command.number,
                    command.color,
                    command.radius,
                )
            )
    return translated


def _luminance(color: QColor) -> float:
    return 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()


def _arrow_geometry(command: ArrowAnnotation) -> tuple[QPointF, QPolygonF] | None:
    dx = command.end.x() - command.start.x()
    dy = command.end.y() - command.start.y()
    length = math.hypot(dx, dy)
    if length < 1.0:
        return None
    unit_x = dx / length
    unit_y = dy / length
    # 短箭头限制箭头头部占比,保留一段箭杆维持方向感。
    head_length = min(max(10.0, command.width * 3.5), length * 0.7)
    head_width = head_length * 0.7
    base = QPointF(
        command.end.x() - unit_x * head_length,
        command.end.y() - unit_y * head_length,
    )
    left = QPointF(
        base.x() - unit_y * head_width / 2,
        base.y() + unit_x * head_width / 2,
    )
    right = QPointF(
        base.x() + unit_y * head_width / 2,
        base.y() - unit_x * head_width / 2,
    )
    return base, QPolygonF([command.end, left, right])


def _pixelated_region(
    source: QImage,
    rect: QRectF,
    source_scale: float,
    block_size: float = 8.0,
) -> tuple[QRectF, QImage] | None:
    physical = QRect(
        math.floor(rect.left() * source_scale),
        math.floor(rect.top() * source_scale),
        math.ceil(rect.width() * source_scale),
        math.ceil(rect.height() * source_scale),
    ).intersected(source.rect())
    if physical.width() < 2 or physical.height() < 2:
        return None
    region = source.copy(physical)
    block = max(2, round(block_size * source_scale))
    # 平滑缩小取块内平均色,遮盖更均匀,不会残留醒目的单像素噪点。
    small = region.scaled(
        max(1, physical.width() // block),
        max(1, physical.height() // block),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    pixelated = small.scaled(
        physical.width(),
        physical.height(),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
    logical = QRectF(
        physical.x() / source_scale,
        physical.y() / source_scale,
        physical.width() / source_scale,
        physical.height() / source_scale,
    )
    return logical, pixelated


def _solid_pen(color: str, width: float) -> QPen:
    return QPen(
        QColor(color),
        width,
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    )


def draw_annotations(
    painter: QPainter,
    annotations: list[Annotation],
    active: Annotation | None = None,
    source: QImage | None = None,
    source_scale: float = 1.0,
) -> None:
    commands: list[Annotation] = list(annotations)
    if active is not None:
        commands.append(active)
    for command in commands:
        if isinstance(command, PenAnnotation):
            painter.setPen(_solid_pen(command.color, command.width))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(command.path)
        elif isinstance(command, ArrowAnnotation):
            geometry = _arrow_geometry(command)
            if geometry is None:
                continue
            base, head = geometry
            painter.setPen(_solid_pen(command.color, command.width))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(command.start, base)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(command.color))
            painter.drawPolygon(head)
        elif isinstance(command, ShapeAnnotation):
            painter.setPen(_solid_pen(command.color, command.width))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if command.shape == "ellipse":
                painter.drawEllipse(command.rect)
            else:
                painter.drawRect(command.rect)
        elif isinstance(command, MosaicAnnotation):
            if source is None:
                continue
            pixelated = _pixelated_region(
                source, command.rect, source_scale, command.block_size
            )
            if pixelated is None:
                continue
            target, image = pixelated
            painter.drawImage(target, image)
        elif isinstance(command, NumberAnnotation):
            radius = command.radius
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(command.color))
            painter.drawEllipse(command.center, radius, radius)
            font = QFont("Microsoft YaHei")
            font.setPixelSize(max(10, round(radius * 1.15)))
            font.setBold(True)
            painter.setFont(font)
            # HSL lightness 会把黄/橙误判成深色底,用感知亮度挑文字颜色。
            text_color = (
                QColor("#111111")
                if _luminance(QColor(command.color)) > 150
                else QColor("white")
            )
            painter.setPen(text_color)
            bounds = QRectF(
                command.center.x() - radius,
                command.center.y() - radius,
                radius * 2,
                radius * 2,
            )
            painter.drawText(
                bounds,
                Qt.AlignmentFlag.AlignCenter,
                str(command.number),
            )
        else:
            font = QFont("Microsoft YaHei")
            font.setPixelSize(command.font_size)
            painter.setFont(font)
            bounds = QRectF(
                command.position.x(),
                command.position.y(),
                command.width,
                10000.0,
            )
            # 折行方式必须与输入框(QTextEdit 默认 WrapAtWordBoundaryOrAnywhere)
            # 一致,超长无空格字符串才不会在提交后突然超宽被裁掉。
            option = QTextOption(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )
            option.setWrapMode(
                QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
            )
            # 一层错位阴影保证文字在同色系背景上仍可读:
            # 亮色文字配深色阴影,深色文字配浅色衬底。
            shadow = (
                QColor(0, 0, 0, 170)
                if _luminance(QColor(command.color)) > 90
                else QColor(255, 255, 255, 170)
            )
            painter.setPen(shadow)
            painter.drawText(bounds.translated(1.0, 1.0), command.text, option)
            painter.setPen(QColor(command.color))
            painter.drawText(bounds, command.text, option)


def render_selection(
    desktop_image: QImage,
    selection: QRectF,
    render_scale: float,
    annotations: list[Annotation],
) -> QImage:
    if selection.width() < 1 or selection.height() < 1:
        return QImage()

    left = max(0, math.floor(selection.left() * render_scale))
    top = max(0, math.floor(selection.top() * render_scale))
    right = min(desktop_image.width(), math.ceil(selection.right() * render_scale))
    bottom = min(
        desktop_image.height(), math.ceil(selection.bottom() * render_scale)
    )
    source_rect = QRect(left, top, max(0, right - left), max(0, bottom - top))
    if source_rect.isEmpty():
        return QImage()

    result = desktop_image.copy(source_rect)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.setTransform(
        QTransform(
            render_scale,
            0.0,
            0.0,
            render_scale,
            -float(left),
            -float(top),
        )
    )
    draw_annotations(
        painter,
        annotations,
        source=desktop_image,
        source_scale=render_scale,
    )
    painter.end()
    return result
