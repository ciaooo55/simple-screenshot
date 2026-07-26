from __future__ import annotations

import os

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter

from simple_screenshot import ocr


def test_join_ocr_words_merges_cjk_keeps_latin_spaces():
    assert ocr.join_ocr_words(["你", "好", "世", "界"]) == "你好世界"
    assert ocr.join_ocr_words(["Hello", "world"]) == "Hello world"
    assert (
        ocr.join_ocr_words(["你", "好", "Hello", "123", "世", "界"])
        == "你好 Hello 123 世界"
    )
    assert ocr.join_ocr_words(["", "你", "", "好"]) == "你好"
    assert ocr.join_ocr_words([]) == ""


def test_image_rgba_bytes_strips_padding_and_orders_channels(qapplication):
    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0))
    image.setPixelColor(0, 0, QColor(255, 0, 0))

    raw, width, height = ocr.image_rgba_bytes(image)

    assert (width, height) == (2, 2)
    assert len(raw) == 2 * 2 * 4
    # RGBA8888:首像素 R=255 G=0 B=0 A=255
    assert raw[0] == 255
    assert raw[1] == 0
    assert raw[2] == 0
    assert raw[3] == 255


def test_is_available_returns_bool_without_raising():
    assert isinstance(ocr.is_available(), bool)


@pytest.mark.skipif(
    not ocr.is_available(), reason="系统没有可用的 OCR 语言引擎"
)
@pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM", "").startswith("offscreen"),
    reason="offscreen 平台加载不了中文字体,渲染出的测试图是豆腐块",
)
def test_recognize_rendered_text_end_to_end(qapplication):
    image = QImage(420, 120, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setPen(QColor("black"))
    font = QFont("Microsoft YaHei")
    font.setPixelSize(28)
    painter.setFont(font)
    # 用无歧义字形的样本:雅黑的小写 l 与大写 I 字形相同,
    # "Hello" 可能被引擎识成 "HeIIo",那不是质量问题。
    painter.drawText(
        image.rect(), Qt.AlignmentFlag.AlignCenter, "你好世界 Demo 123"
    )
    painter.end()

    outcome = ocr.recognize_image(image)

    assert "你好世界" in outcome.text
    assert "Demo" in outcome.text
    assert "123" in outcome.text
    assert outcome.line_count >= 1


def test_false_availability_is_not_cached():
    original = ocr._availability
    try:
        # False 不缓存:装好语言包后无需重启应用即可恢复。
        ocr._availability = False
        first = ocr.is_available()
        assert isinstance(first, bool)
        if first:
            # 本机引擎可用:False 被重探测纠正,且 True 会被缓存。
            assert ocr._availability is True
    finally:
        ocr._availability = original
