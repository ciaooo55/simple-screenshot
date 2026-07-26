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
        if first and ocr._rapid_available() and not ocr._rapid_failed:
            # 内置引擎在场:True 来自轻量探测,不写缓存——
            # 引擎初始化失败后,下次查询才能落到系统引擎真实检测。
            assert ocr._availability is False
        elif first:
            # 系统引擎路径:经过真实验证的 True 才缓存。
            assert ocr._availability is True
    finally:
        ocr._availability = original


def test_image_bgr_array_channel_order(qapplication):
    np = pytest.importorskip("numpy")
    from PySide6.QtGui import QColor, QImage

    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0))
    image.setPixelColor(0, 0, QColor(255, 0, 0))  # 纯红

    array = ocr.image_bgr_array(image)

    assert array.shape == (2, 2, 3)
    assert array.dtype == np.uint8
    # BGR:红色像素应是 [0, 0, 255]
    assert list(array[0, 0]) == [0, 0, 255]
    assert list(array[1, 1]) == [0, 0, 0]


def test_rapid_failure_falls_back_to_windows(qapplication, monkeypatch):
    from PySide6.QtGui import QColor, QImage

    calls: list[str] = []

    def broken_rapid(image):
        calls.append("rapid")
        raise RuntimeError("显卡驱动炸了")

    def fake_windows(image):
        calls.append("windows")
        return ocr.OcrOutcome(text="fallback", line_count=1)

    monkeypatch.setattr(ocr, "_recognize_with_rapid", broken_rapid)
    monkeypatch.setattr(ocr, "_recognize_with_windows", fake_windows)

    image = QImage(10, 10, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    outcome = ocr.recognize_image(image)

    assert calls == ["rapid", "windows"]
    assert outcome.text == "fallback"


def test_rapid_availability_probe_is_lightweight():
    # 只探测包是否存在,不应触发引擎初始化。
    assert isinstance(ocr._rapid_available(), bool)


@pytest.mark.skipif(
    not ocr._rapid_available(), reason="内置引擎未安装"
)
@pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM", "").startswith("offscreen"),
    reason="offscreen 平台字体渲染不可靠",
)
def test_english_word_spaces_preserved(qapplication):
    from PySide6.QtGui import QColor, QFont, QImage, QPainter

    image = QImage(760, 46, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setPen(QColor("#222222"))
    font = QFont("Segoe UI")
    font.setPixelSize(14)
    painter.setFont(font)
    painter.drawText(
        8, 30, "error: connection timeout after 30 seconds retry limit"
    )
    painter.end()

    outcome = ocr.recognize_image(image)

    # 8 个词的空格必须保留,也不允许过切分。
    assert 7 <= len(outcome.text.split()) <= 9
    assert "connection" in outcome.text
    assert "timeout" in outcome.text
