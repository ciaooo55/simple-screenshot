from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFocusEvent, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from .config import AppSettings, CONFIG_VERSION
from .hotkeys import Hotkey, hotkey_from_key_event, parse_hotkey


class HotkeyEdit(QLineEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("点击后直接按下所需快捷键")
        self._hotkey = parse_hotkey("Alt+A")
        self._capturing = False
        self._previous_text = self._hotkey.display
        self.setText(self._hotkey.display)

    def set_hotkey(self, value: str) -> None:
        self._hotkey = parse_hotkey(value)
        self._previous_text = self._hotkey.display
        self._capturing = False
        self.setText(self._hotkey.display)

    def hotkey(self) -> Hotkey:
        return self._hotkey

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._begin_capture()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._capturing:
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key.Key_Escape:
            self._cancel_capture()
            event.accept()
            return
        try:
            hotkey = hotkey_from_key_event(event)
        except ValueError as exc:
            self.setText("请按组合键…")
            QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()), str(exc), self)
            event.accept()
            return
        self._hotkey = hotkey
        self._previous_text = hotkey.display
        self._capturing = False
        self.setText(hotkey.display)
        event.accept()

    def focusOutEvent(self, event: QFocusEvent) -> None:
        if self._capturing:
            self._cancel_capture()
        super().focusOutEvent(event)

    def _begin_capture(self) -> None:
        self._previous_text = self._hotkey.display
        self._capturing = True
        self.setText("请按快捷键…")
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.selectAll()

    def _cancel_capture(self) -> None:
        self._capturing = False
        self.setText(self._previous_text)


class SettingsDialog(QDialog):
    def __init__(
        self,
        save_callback: Callable[[AppSettings], tuple[bool, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.save_callback = save_callback
        self.setWindowTitle("截图工具设置")
        self.setMinimumWidth(520)
        self.setModal(False)

        root = QVBoxLayout(self)
        intro = QLabel(
            "点击快捷键输入框，然后按下一个按键或组合键。设置保存后立即生效。",
            self,
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.copy_hotkey_edit = HotkeyEdit(self)
        self.save_hotkey_edit = HotkeyEdit(self)
        form.addRow("截图并复制：", self.copy_hotkey_edit)
        form.addRow("截图并保存：", self.save_hotkey_edit)

        directory_row = QWidget(self)
        directory_layout = QHBoxLayout(directory_row)
        directory_layout.setContentsMargins(0, 0, 0, 0)
        self.directory_edit = QLineEdit(directory_row)
        browse_button = QPushButton("浏览…", directory_row)
        browse_button.clicked.connect(self._browse_directory)
        directory_layout.addWidget(self.directory_edit, 1)
        directory_layout.addWidget(browse_button)
        form.addRow("保存目录：", directory_row)

        self.startup_checkbox = QCheckBox("登录 Windows 后自动启动", self)
        form.addRow("开机启动：", self.startup_checkbox)
        root.addLayout(form)

        note = QLabel(
            "截图时：单击吸附窗口，拖动自由框选；选区边缘可微调；"
            "方向键微调（Shift 为 10px）；双击或 Enter 完成默认动作；"
            "Ctrl+C 复制，Ctrl+S 保存，Esc 取消。",
            self,
        )
        note.setStyleSheet("color: #666;")
        note.setWordWrap(True)
        root.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        save_button.setText("保存")
        cancel_button.setText("取消")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._settings: AppSettings | None = None

    def load_settings(self, settings: AppSettings) -> None:
        self._settings = settings
        self.copy_hotkey_edit.set_hotkey(settings.copy_hotkey)
        self.save_hotkey_edit.set_hotkey(settings.save_hotkey)
        self.directory_edit.setText(settings.save_directory)
        self.startup_checkbox.setChecked(settings.start_with_windows)

    def show_with_settings(self, settings: AppSettings) -> None:
        self.load_settings(settings)
        self.show()
        self.raise_()
        self.activateWindow()

    def _browse_directory(self) -> None:
        current = self.directory_edit.text().strip()
        selected = QFileDialog.getExistingDirectory(
            self,
            "选择截图保存目录",
            current or str(Path.cwd()),
        )
        if selected:
            self.directory_edit.setText(selected)

    def _save(self) -> None:
        directory_text = self.directory_edit.text().strip()
        if not directory_text:
            QMessageBox.warning(self, "设置无效", "保存目录不能为空。")
            return
        try:
            directory = Path(directory_text).expanduser().resolve()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "设置无效", f"保存目录无效：{exc}")
            return

        copy_hotkey = self.copy_hotkey_edit.hotkey()
        save_hotkey = self.save_hotkey_edit.hotkey()
        if copy_hotkey == save_hotkey:
            QMessageBox.warning(self, "设置无效", "复制和保存快捷键不能相同。")
            return

        settings = AppSettings(
            version=CONFIG_VERSION,
            copy_hotkey=copy_hotkey.display,
            save_hotkey=save_hotkey.display,
            save_directory=str(directory),
            start_with_windows=self.startup_checkbox.isChecked(),
        )
        success, message = self.save_callback(settings)
        if not success:
            QMessageBox.warning(self, "设置保存失败", message)
            return
        self._settings = settings
        self.accept()
