from __future__ import annotations

from PySide6.QtGui import QGuiApplication

from simple_screenshot.text_result_dialog import TextResultDialog


def test_dialog_shows_text_and_copies_all(qapplication):
    dialog = TextResultDialog("你好世界\nHello 123")

    assert "2 行" in dialog.windowTitle()
    assert dialog.text_edit.toPlainText() == "你好世界\nHello 123"

    dialog.copy_all()
    assert QGuiApplication.clipboard().text() == "你好世界\nHello 123"
    assert dialog.copy_button.text() == "已复制"
    dialog.close()
