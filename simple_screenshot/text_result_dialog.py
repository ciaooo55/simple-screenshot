from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class TextResultDialog(QDialog):
    """展示 OCR 识别结果:可编辑、可选中复制,置顶不被贴图挡住。"""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        line_count = len(text.splitlines()) or 1
        char_count = len(text.replace("\n", ""))
        self.setWindowTitle(f"识别结果 · {line_count} 行 {char_count} 字")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(440, 320)

        root = QVBoxLayout(self)
        self.text_edit = QPlainTextEdit(self)
        self.text_edit.setPlainText(text)
        root.addWidget(self.text_edit)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.copy_button = QPushButton("复制全部", self)
        close_button = QPushButton("关闭", self)
        self.copy_button.clicked.connect(self.copy_all)
        close_button.clicked.connect(self.close)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

    def copy_all(self) -> None:
        QGuiApplication.clipboard().setText(self.text_edit.toPlainText())
        self.copy_button.setText("已复制")
