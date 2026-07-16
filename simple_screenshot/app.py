from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QTimer, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from .capture import CaptureOverlay, capture_virtual_desktop
from .config import AppSettings, SettingsStore, default_settings
from .hotkeys import HotkeyManager, parse_hotkey
from .output import save_png_atomic
from .settings_dialog import SettingsDialog
from .single_instance import SingleInstance
from .startup import set_start_with_windows


APP_TITLE = "简易截图工具"


def bundled_resource(relative_path: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root / relative_path


def create_app_icon() -> QIcon:
    icon = QIcon(str(bundled_resource("assets/app.ico")))
    if not icon.isNull():
        return icon

    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(QColor("#1677ff"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4, 4, 56, 56, 13, 13)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(
        QPen(
            QColor("white"),
            5,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
    painter.drawLine(18, 26, 18, 18)
    painter.drawLine(18, 18, 26, 18)
    painter.drawLine(38, 18, 46, 18)
    painter.drawLine(46, 18, 46, 26)
    painter.drawLine(18, 38, 18, 46)
    painter.drawLine(18, 46, 26, 46)
    painter.drawLine(38, 46, 46, 46)
    painter.drawLine(46, 38, 46, 46)
    painter.end()
    return QIcon(pixmap)


class AppController:
    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.store = SettingsStore()
        self.settings = self.store.load()
        self.icon = create_app_icon()
        self.app.setWindowIcon(self.icon)
        self.hotkeys = HotkeyManager()
        self.hotkeys.activated.connect(self.request_capture)
        self.overlay: CaptureOverlay | None = None
        self._capture_pending = False
        self._closed = False
        self._startup_warnings: list[str] = []
        if self.store.last_warning:
            self._startup_warnings.append(self.store.last_warning)

        self.settings_dialog = SettingsDialog(self.apply_settings)
        self.settings_dialog.setWindowIcon(self.icon)
        self.tray = QSystemTrayIcon(self.icon, self.app)
        self.tray.setToolTip(APP_TITLE)
        self.tray.setContextMenu(self._create_tray_menu())
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

        self._activate_initial_settings()
        QTimer.singleShot(650, self._show_startup_notice)
        self.app.aboutToQuit.connect(self.close)

    def _create_tray_menu(self) -> QMenu:
        menu = QMenu()
        copy_action = QAction("截图并复制", menu)
        save_action = QAction("截图并保存", menu)
        settings_action = QAction("设置…", menu)
        self.startup_action = QAction("开机启动", menu)
        self.startup_action.setCheckable(True)
        exit_action = QAction("退出", menu)

        copy_action.triggered.connect(lambda: self.request_capture("copy"))
        save_action.triggered.connect(lambda: self.request_capture("save"))
        settings_action.triggered.connect(self.show_settings)
        self.startup_action.triggered.connect(self._toggle_startup)
        exit_action.triggered.connect(self.quit)

        menu.addAction(copy_action)
        menu.addAction(save_action)
        menu.addSeparator()
        menu.addAction(settings_action)
        menu.addAction(self.startup_action)
        menu.addSeparator()
        menu.addAction(exit_action)
        return menu

    def _activate_initial_settings(self) -> None:
        try:
            copy_hotkey = parse_hotkey(self.settings.copy_hotkey)
            save_hotkey = parse_hotkey(self.settings.save_hotkey)
        except ValueError as exc:
            self._startup_warnings.append(f"快捷键设置无效，已恢复默认值：{exc}")
            self.settings = default_settings(self.store.base_dir)
            copy_hotkey = parse_hotkey(self.settings.copy_hotkey)
            save_hotkey = parse_hotkey(self.settings.save_hotkey)
            try:
                self.store.save(self.settings)
            except OSError as save_error:
                self._startup_warnings.append(f"默认设置保存失败：{save_error}")

        registered, message = self.hotkeys.apply(copy_hotkey, save_hotkey)
        if not registered:
            self._startup_warnings.append(message)

        try:
            set_start_with_windows(self.settings.start_with_windows)
        except OSError as exc:
            self._startup_warnings.append(f"开机启动设置应用失败，已关闭：{exc}")
            self.settings = self.settings.updated(start_with_windows=False)
            try:
                self.store.save(self.settings)
            except OSError as save_error:
                self._startup_warnings.append(f"设置保存失败：{save_error}")
        self._sync_tray_state()

    def show_settings(self) -> None:
        if self.overlay is not None:
            return
        self.settings_dialog.show_with_settings(self.settings)

    def apply_settings(self, new_settings: AppSettings) -> tuple[bool, str]:
        old_settings = self.settings
        try:
            copy_hotkey = parse_hotkey(new_settings.copy_hotkey)
            save_hotkey = parse_hotkey(new_settings.save_hotkey)
            old_copy = parse_hotkey(old_settings.copy_hotkey)
            old_save = parse_hotkey(old_settings.save_hotkey)
        except ValueError as exc:
            return False, str(exc)

        registered, message = self.hotkeys.apply(copy_hotkey, save_hotkey)
        if not registered:
            return False, message

        try:
            set_start_with_windows(new_settings.start_with_windows)
        except OSError as exc:
            self.hotkeys.apply(old_copy, old_save)
            return False, f"开机启动设置失败：{exc}"

        try:
            self.store.save(new_settings)
        except OSError as exc:
            self.hotkeys.apply(old_copy, old_save)
            try:
                set_start_with_windows(old_settings.start_with_windows)
            except OSError:
                pass
            return False, f"设置文件保存失败：{exc}"

        self.settings = new_settings
        self._sync_tray_state()
        self.notify("设置已保存", "新的快捷键和保存位置已经生效。")
        return True, ""

    def request_capture(self, action: str) -> None:
        if action not in {"copy", "save"}:
            return
        if self.overlay is not None or self._capture_pending:
            return
        self._capture_pending = True
        self.settings_dialog.hide()
        QTimer.singleShot(160, lambda: self._begin_capture(action))

    def _begin_capture(self, action: str) -> None:
        self._capture_pending = False
        if self.overlay is not None:
            return
        try:
            self.app.processEvents()
            desktop = capture_virtual_desktop()
            overlay = CaptureOverlay(desktop, action)
            self.overlay = overlay
            overlay.completed.connect(self._capture_completed)
            overlay.cancelled.connect(self._capture_cancelled)
            overlay.start()
        except Exception as exc:
            self.overlay = None
            self.notify("截图失败", str(exc), warning=True)

    def _capture_completed(self, image, action: str) -> None:  # type: ignore[no-untyped-def]
        self.overlay = None
        if action == "copy":
            try:
                self.app.clipboard().setImage(image)
                self.notify("截图成功", "已复制到剪贴板，可以直接粘贴到聊天软件。")
            except Exception as exc:
                self.notify("复制失败", str(exc), warning=True)
            return

        try:
            target = save_png_atomic(image, Path(self.settings.save_directory))
            self.notify("截图已保存", str(target))
        except Exception as exc:
            self.notify("保存失败", f"无法写入截图文件：{exc}", warning=True)

    def _capture_cancelled(self) -> None:
        self.overlay = None

    def _toggle_startup(self, checked: bool) -> None:
        candidate = self.settings.updated(start_with_windows=checked)
        success, message = self.apply_settings(candidate)
        if not success:
            self._sync_tray_state()
            self.notify("开机启动设置失败", message, warning=True)

    def _sync_tray_state(self) -> None:
        blocker = QSignalBlocker(self.startup_action)
        self.startup_action.setChecked(self.settings.start_with_windows)
        del blocker

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_settings()

    def _show_startup_notice(self) -> None:
        hotkey_text = (
            f"{self.settings.copy_hotkey} 截图并复制；"
            f"{self.settings.save_hotkey} 截图并保存。"
        )
        if self._startup_warnings:
            details = "\n".join(self._startup_warnings)
            self.notify("截图工具已启动，但有设置需要处理", f"{hotkey_text}\n{details}", True)
        else:
            self.notify("截图工具已启动", hotkey_text)

    def notify(self, title: str, message: str, warning: bool = False) -> None:
        icon = (
            QSystemTrayIcon.MessageIcon.Warning
            if warning
            else QSystemTrayIcon.MessageIcon.Information
        )
        self.tray.showMessage(title, message, icon, 4500)

    def handle_second_instance(self) -> None:
        self.notify(
            "截图工具正在运行",
            f"{self.settings.copy_hotkey} 截图并复制；{self.settings.save_hotkey} 截图并保存。",
        )

    def quit(self) -> None:
        if self.overlay is not None:
            self.overlay.cancel()
            self.overlay = None
        self.settings_dialog.close()
        self.app.quit()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.hotkeys.close()
        self.tray.hide()


def run() -> int:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "SimpleScreenshot.1"
        )
    except (AttributeError, OSError):
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("SimpleScreenshot")
    app.setApplicationDisplayName(APP_TITLE)
    app.setOrganizationName("SimpleScreenshot")
    app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, APP_TITLE, "当前系统没有可用的通知区域，程序无法启动。")
        return 1

    instance = SingleInstance()
    try:
        if not instance.claim_or_notify():
            return 0
    except RuntimeError as exc:
        QMessageBox.critical(None, APP_TITLE, str(exc))
        return 1

    controller = AppController(app)
    instance.activate_requested.connect(controller.handle_second_instance)
    return app.exec()
