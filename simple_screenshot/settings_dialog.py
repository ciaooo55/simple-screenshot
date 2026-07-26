from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
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

from .config import AppSettings, CONFIG_VERSION, default_settings
from .hotkeys import Hotkey, hotkey_from_key_event, parse_hotkey


class HotkeyEdit(QLineEdit):
    # 录制开始/结束时发出;录制期间需要临时挂起全局热键,
    # 否则按下现有热键会被系统拦截去截图,没法互换或重录同一组合键。
    capture_toggled = Signal(bool)

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
        self._set_capturing(False)
        self.setText(self._hotkey.display)

    def is_capturing(self) -> bool:
        return self._capturing

    def _set_capturing(self, value: bool) -> None:
        if self._capturing == value:
            return
        self._capturing = value
        self.capture_toggled.emit(value)

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
        if event.key() in {
            Qt.Key.Key_Control,
            Qt.Key.Key_Shift,
            Qt.Key.Key_Alt,
            Qt.Key.Key_Meta,
        }:
            # 组合键要先按住修饰键,这一步不是错误,安静等主键。
            self.setText("请按组合键…")
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
        self._set_capturing(False)
        self.setText(hotkey.display)
        event.accept()

    def focusOutEvent(self, event: QFocusEvent) -> None:
        if self._capturing:
            self._cancel_capture()
        super().focusOutEvent(event)

    def _begin_capture(self) -> None:
        self._previous_text = self._hotkey.display
        self._set_capturing(True)
        self.setText("请按快捷键…")
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.selectAll()

    def _cancel_capture(self) -> None:
        self._set_capturing(False)
        self.setText(self._previous_text)


class SettingsDialog(QDialog):
    # 任一快捷键输入框在录制时为 True;焦点在输入框之间切换会交错
    # 触发开始/取消,所以聚合后再对外发,避免误恢复全局热键。
    hotkey_capture_toggled = Signal(bool)

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
        self.pin_hotkey_edit = HotkeyEdit(self)
        for edit in (
            self.copy_hotkey_edit,
            self.save_hotkey_edit,
            self.pin_hotkey_edit,
        ):
            edit.capture_toggled.connect(self._on_hotkey_capture_toggled)
        form.addRow("截图并复制：", self.copy_hotkey_edit)
        form.addRow("截图并保存：", self.save_hotkey_edit)
        form.addRow("截图并钉住：", self.pin_hotkey_edit)

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
        self.hide_pins_checkbox = QCheckBox(
            "截图时暂时隐藏已有贴图（避免旧贴图被截进新图）", self
        )
        form.addRow("贴图：", self.hide_pins_checkbox)
        root.addLayout(form)

        note = QLabel(
            "<b>框选</b>：单击吸附窗口，拖动自由框选（Shift 正方形）；"
            "Ctrl+A 全屏，R 恢复上次选区；放大镜取色，C 复制颜色值。<br>"
            "<b>调整</b>：方向键移动选区，Ctrl+方向键调整大小（加 Shift 步长 10px），"
            "拖动边角手柄微调。<br>"
            "<b>标注</b>：选区确定后默认画笔直接涂画，G 荧光笔高亮不遮字，"
            "V 切回选择工具可拖动选区；滚轮调画笔粗细 / 文字字号，"
            "Shift 约束正圆与 45° 箭头；Ctrl+Z 撤销、Ctrl+Y 重做；"
            "F1 查看全部快捷键。<br>"
            "<b>完成</b>：双击或 Enter 执行默认动作；Ctrl+C 复制、Ctrl+S 保存、"
            "Ctrl+Shift+S 另存为、Ctrl+D 钉住、W 识别选区文字；"
            "右键逐级返回，Esc 取消（拖拽中只取消当前一笔）。<br>"
            "<b>贴图</b>：拖动移动（贴边自动吸附），Ctrl+拖动拖出为文件，"
            "滚轮以光标为中心缩放，Ctrl+滚轮调透明度，方向键微调，"
            "双击或 Ctrl+0 还原，右键可开鼠标穿透（托盘恢复）或识别文字，"
            "Esc 关闭；托盘菜单可直接贴剪贴板里的图片。",
            self,
        )
        note.setTextFormat(Qt.TextFormat.RichText)
        note.setStyleSheet("color: #666;")
        note.setWordWrap(True)
        root.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults,
            parent=self,
        )
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        restore_button = buttons.button(
            QDialogButtonBox.StandardButton.RestoreDefaults
        )
        save_button.setText("保存")
        cancel_button.setText("取消")
        restore_button.setText("恢复默认")
        restore_button.setToolTip("把上方各项填回默认值;点“保存”后才生效")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        restore_button.clicked.connect(self._restore_defaults)
        root.addWidget(buttons)

        self._settings: AppSettings | None = None

    def _on_hotkey_capture_toggled(self, _active: bool) -> None:
        self.hotkey_capture_toggled.emit(
            self.copy_hotkey_edit.is_capturing()
            or self.save_hotkey_edit.is_capturing()
            or self.pin_hotkey_edit.is_capturing()
        )

    def load_settings(self, settings: AppSettings) -> None:
        self._settings = settings
        self.copy_hotkey_edit.set_hotkey(settings.copy_hotkey)
        self.save_hotkey_edit.set_hotkey(settings.save_hotkey)
        self.pin_hotkey_edit.set_hotkey(settings.pin_hotkey)
        self.directory_edit.setText(settings.save_directory)
        self.startup_checkbox.setChecked(settings.start_with_windows)
        self.hide_pins_checkbox.setChecked(settings.hide_pins_on_capture)

    def show_with_settings(self, settings: AppSettings) -> None:
        self.load_settings(settings)
        self.show()
        self.raise_()
        self.activateWindow()

    def _restore_defaults(self) -> None:
        defaults = default_settings()
        self.copy_hotkey_edit.set_hotkey(defaults.copy_hotkey)
        self.save_hotkey_edit.set_hotkey(defaults.save_hotkey)
        self.pin_hotkey_edit.set_hotkey(defaults.pin_hotkey)
        self.directory_edit.setText(defaults.save_directory)
        self.startup_checkbox.setChecked(defaults.start_with_windows)
        self.hide_pins_checkbox.setChecked(defaults.hide_pins_on_capture)

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
        try:
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / ".simple_screenshot_write_test.tmp"
            probe.write_bytes(b"")
            probe.unlink()
        except OSError as exc:
            QMessageBox.warning(
                self,
                "设置无效",
                f"保存目录不可写，请换一个位置：{exc}",
            )
            return

        copy_hotkey = self.copy_hotkey_edit.hotkey()
        save_hotkey = self.save_hotkey_edit.hotkey()
        pin_hotkey = self.pin_hotkey_edit.hotkey()
        if len({copy_hotkey, save_hotkey, pin_hotkey}) != 3:
            QMessageBox.warning(self, "设置无效", "三个快捷键不能相同。")
            return

        settings = AppSettings(
            version=CONFIG_VERSION,
            copy_hotkey=copy_hotkey.display,
            save_hotkey=save_hotkey.display,
            pin_hotkey=pin_hotkey.display,
            save_directory=str(directory),
            start_with_windows=self.startup_checkbox.isChecked(),
            hide_pins_on_capture=self.hide_pins_checkbox.isChecked(),
        )
        success, message = self.save_callback(settings)
        if not success:
            QMessageBox.warning(self, "设置保存失败", message)
            return
        self._settings = settings
        self.accept()
