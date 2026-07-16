from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TypeAlias

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QTransform


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


Annotation: TypeAlias = PenAnnotation | TextAnnotation


def draw_annotations(
    painter: QPainter,
    annotations: list[Annotation],
    active_pen: PenAnnotation | None = None,
) -> None:
    commands: list[Annotation] = list(annotations)
    if active_pen is not None:
        commands.append(active_pen)
    for command in commands:
        if isinstance(command, PenAnnotation):
            pen = QPen(
                QColor(command.color),
                command.width,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(command.path)
        else:
            painter.setPen(QColor(command.color))
            font = QFont("Microsoft YaHei")
            font.setPixelSize(command.font_size)
            painter.setFont(font)
            bounds = QRectF(
                command.position.x(),
                command.position.y(),
                command.width,
                10000.0,
            )
            painter.drawText(
                bounds,
                Qt.AlignmentFlag.AlignLeft
                | Qt.AlignmentFlag.AlignTop
                | Qt.TextFlag.TextWordWrap,
                command.text,
            )


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
    draw_annotations(painter, annotations)
    painter.end()
    return result
