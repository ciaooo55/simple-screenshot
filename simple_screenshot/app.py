from __future__ import annotations

import ctypes
import logging
import multiprocessing
import os
import subprocess
import sys
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QIODevice,
    QObject,
    QRect,
    QRectF,
    QSignalBlocker,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QGuiApplication,
    QIcon,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from . import __version__, ocr
from .capture import CapturedDesktop, CaptureOverlay, capture_virtual_desktop
from .capture_session import CaptureSessionWindow
from .config import AppSettings, SettingsStore, default_settings
from .diagnostics import configure_diagnostics
from .hotkeys import Hotkey, HotkeyManager, parse_hotkey
from .output import (
    cleanup_stale_drag_copies,
    save_png_atomic,
    unique_screenshot_path,
)
from .pin_window import PinWindow
from .settings_dialog import SettingsDialog
from .single_instance import SingleInstance
from .startup import is_start_with_windows_enabled, set_start_with_windows


APP_TITLE = "简易截图工具"
PROJECT_URL = "https://github.com/ciaooo55/simple-screenshot"
AUTHOR = "ciaooo55"
logger = logging.getLogger(__name__)


class _OcrWorker(QObject):
    """跨线程信使:工作线程发射,槽在主线程执行(自动排队连接)。"""

    finished = Signal(object)
    failed = Signal(str)


class ResilientApplication(QApplication):
    """Keep a Python UI exception from terminating the tray process silently."""

    ui_error = Signal(str)

    def notify(self, receiver, event) -> bool:  # type: ignore[no-untyped-def]
        try:
            return super().notify(receiver, event)
        except Exception:
            logger.exception("界面事件处理失败，已拦截并继续运行")
            QTimer.singleShot(
                0,
                lambda: self.ui_error.emit(
                    "操作没有完成，但程序已继续运行；诊断信息已写入 app.log。"
                ),
            )
            return False


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
        self.pin_windows: list[PinWindow] = []
        self.capture_sessions: list[CaptureSessionWindow] = []
        self._pins_hidden_for_capture: list[PinWindow] = []
        self._ocr_busy = False
        self._ocr_worker: _OcrWorker | None = None
        self._ocr_target: CaptureOverlay | PinWindow | CaptureSessionWindow | None = None
        self._ocr_executor: ProcessPoolExecutor | None = None
        self._ocr_process_ready = False
        self._last_save_as_dir: Path | None = None
        try:
            cleanup_stale_drag_copies()
        except OSError:
            pass
        self._capture_pending = False
        self._closed = False
        self._last_saved_path: Path | None = None
        self._last_image: QImage | None = None
        self._settings_was_visible = False
        self._startup_warnings: list[str] = []
        if self.store.last_warning:
            self._startup_warnings.append(self.store.last_warning)

        self.settings_dialog = SettingsDialog(self.apply_settings)
        self.settings_dialog.setWindowIcon(self.icon)
        # 录制快捷键的瞬间放开系统级注册,按现有热键才能被输入框收到
        # (否则想互换两个热键会直接触发截图);录制结束立即恢复。
        self.settings_dialog.hotkey_capture_toggled.connect(
            self._on_hotkey_capture_toggled
        )
        self.tray = QSystemTrayIcon(self.icon, self.app)
        self.tray.setContextMenu(self._create_tray_menu())
        self.tray.activated.connect(self._tray_activated)
        self.tray.messageClicked.connect(self._notification_clicked)
        self.tray.show()
        if isinstance(self.app, ResilientApplication):
            self.app.ui_error.connect(
                lambda message: self.notify("操作出现异常", message, warning=True)
            )
        # 单击托盘立即截图;双击打开设置。两者靠双击间隔计时器区分。
        self._tray_click_timer = QTimer(self.app)
        self._tray_click_timer.setSingleShot(True)
        self._tray_click_timer.setInterval(
            QApplication.doubleClickInterval()
        )
        self._tray_click_timer.timeout.connect(
            lambda: self.request_capture("copy")
        )
        self._ocr_idle_timer = QTimer(self.app)
        self._ocr_idle_timer.setSingleShot(True)
        self._ocr_idle_timer.setInterval(5 * 60 * 1000)
        self._ocr_idle_timer.timeout.connect(self._release_idle_ocr_process)

        self._activate_initial_settings()
        QTimer.singleShot(650, self._show_startup_notice)
        # OCR 只在用户明确按 W 后启动隔离进程。避免登录 Windows 时
        # 无缘无故加载数百 MB 模型，也避开显卡驱动的启动期原生崩溃。
        self.app.aboutToQuit.connect(self.close)

    def _create_tray_menu(self) -> QMenu:
        menu = QMenu()
        copy_action = QAction("截图并复制", menu)
        save_action = QAction("截图并保存", menu)
        pin_action = QAction("截图并钉住", menu)
        fullscreen_action = QAction("全屏截图", menu)
        self.pin_clipboard_action = QAction("贴图剪贴板图片", menu)
        self.unlock_pins_action = QAction("恢复贴图可点击", menu)
        self.save_last_action = QAction("保存最近一张截图", menu)
        self.close_pins_action = QAction("关闭所有贴图", menu)
        folder_action = QAction("打开截图文件夹", menu)
        settings_action = QAction("设置…", menu)
        self.startup_action = QAction("开机启动", menu)
        self.startup_action.setCheckable(True)
        about_action = QAction("关于", menu)
        exit_action = QAction("退出", menu)

        copy_action.triggered.connect(lambda: self.request_capture("copy"))
        save_action.triggered.connect(lambda: self.request_capture("save"))
        pin_action.triggered.connect(lambda: self.request_capture("pin"))
        fullscreen_action.triggered.connect(
            lambda: self.request_capture("copy", fullscreen=True)
        )
        self.pin_clipboard_action.triggered.connect(self.pin_clipboard_image)
        self.unlock_pins_action.triggered.connect(self.restore_pins_clickable)
        self.save_last_action.triggered.connect(self._save_last_image)
        self.close_pins_action.triggered.connect(self.close_all_pins)
        folder_action.triggered.connect(self.open_save_directory)
        settings_action.triggered.connect(self.show_settings)
        self.startup_action.triggered.connect(self._toggle_startup)
        about_action.triggered.connect(self.show_about)
        exit_action.triggered.connect(self.quit)

        menu.addAction(copy_action)
        menu.addAction(save_action)
        menu.addAction(pin_action)
        menu.addAction(fullscreen_action)
        menu.addSeparator()
        menu.addAction(self.pin_clipboard_action)
        menu.addAction(self.unlock_pins_action)
        menu.addAction(self.save_last_action)
        menu.addAction(self.close_pins_action)
        menu.addAction(folder_action)
        menu.addAction(settings_action)
        menu.addAction(self.startup_action)
        menu.addSeparator()
        menu.addAction(about_action)
        menu.addSeparator()
        menu.addAction(exit_action)
        menu.aboutToShow.connect(self._sync_tray_menu)
        return menu

    def _sync_tray_menu(self) -> None:
        actual_startup = is_start_with_windows_enabled()
        if actual_startup != self.settings.start_with_windows:
            self.settings = self.settings.updated(start_with_windows=actual_startup)
            try:
                self.store.save(self.settings)
            except OSError:
                pass
            self._sync_tray_state()
        self.save_last_action.setEnabled(self._last_image is not None)
        self.close_pins_action.setEnabled(bool(self.pin_windows))
        self.unlock_pins_action.setEnabled(
            any(pin.click_through for pin in self.pin_windows)
        )

    def restore_pins_clickable(self) -> None:
        for pin in self.pin_windows:
            pin.set_click_through(False)

    def _save_last_image(self) -> None:
        if self._last_image is not None:
            self._save_image(self._last_image)

    def pin_clipboard_image(self) -> None:
        """把剪贴板里的图片(任意来源)钉成置顶贴图。"""
        image = self.app.clipboard().image()
        if image.isNull():
            self.notify(
                "剪贴板里没有图片",
                "先复制一张图片(网页右键复制、微信图片等),再用本功能贴到屏幕上。",
                warning=True,
            )
            return
        self._create_pin_window(QImage(image), QCursor.pos(), fit_to_screen=True)

    def _parse_hotkey_mapping(self, settings: AppSettings) -> dict[str, Hotkey]:
        return {
            "copy": parse_hotkey(settings.copy_hotkey),
            "save": parse_hotkey(settings.save_hotkey),
            "pin": parse_hotkey(settings.pin_hotkey),
        }

    def _activate_initial_settings(self) -> None:
        try:
            mapping = self._parse_hotkey_mapping(self.settings)
        except ValueError as exc:
            self._startup_warnings.append(f"快捷键设置无效，已恢复默认值：{exc}")
            self.settings = default_settings(self.store.base_dir)
            mapping = self._parse_hotkey_mapping(self.settings)
            try:
                self.store.save(self.settings)
            except OSError as save_error:
                self._startup_warnings.append(f"默认设置保存失败：{save_error}")

        registered, message = self.hotkeys.apply(mapping)
        if not registered:
            self._startup_warnings.append(message)
            # 逐键降级:哪个键被占用就跳过哪个,其余热键必须保住。
            # apply 失败时会恢复到上一次成功的组合,所以增量尝试是安全的。
            working: dict[str, Hotkey] = {}
            for action in ("copy", "save", "pin"):
                candidate = dict(working)
                candidate[action] = mapping[action]
                ok, fail_message = self.hotkeys.apply(candidate)
                if ok:
                    working = candidate
                elif fail_message != message:
                    self._startup_warnings.append(fail_message)

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

    def _on_hotkey_capture_toggled(self, capturing: bool) -> None:
        if capturing:
            self.hotkeys.suspend()
        else:
            self.hotkeys.resume()

    def show_settings(self) -> None:
        if self.overlay is not None or self._capture_pending:
            return
        if self.settings_dialog.isVisible():
            # 已经打开时只前置,不重置输入框,保住未保存的编辑。
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
            return
        self.settings_dialog.show_with_settings(self.settings)

    def apply_settings(
        self,
        new_settings: AppSettings,
        notice: str | None = None,
    ) -> tuple[bool, str]:
        old_settings = self.settings
        try:
            new_mapping = self._parse_hotkey_mapping(new_settings)
            old_mapping = self._parse_hotkey_mapping(old_settings)
        except ValueError as exc:
            return False, str(exc)

        registered, message = self.hotkeys.apply(new_mapping)
        if not registered:
            return False, message

        try:
            set_start_with_windows(new_settings.start_with_windows)
        except OSError as exc:
            self.hotkeys.apply(old_mapping)
            return False, f"开机启动设置失败：{exc}"

        try:
            self.store.save(new_settings)
        except OSError as exc:
            self.hotkeys.apply(old_mapping)
            try:
                set_start_with_windows(old_settings.start_with_windows)
            except OSError:
                pass
            return False, f"设置文件保存失败：{exc}"

        self.settings = new_settings
        self._sync_tray_state()
        self.notify("设置已保存", notice or "新的快捷键和保存位置已经生效。")
        return True, ""

    def request_capture(self, action: str, fullscreen: bool = False) -> None:
        if action not in {"copy", "save", "pin"}:
            return
        if self.overlay is not None or self._capture_pending:
            return
        self._capture_pending = True
        self._settings_was_visible = self.settings_dialog.isVisible()
        self.settings_dialog.hide()
        if self.settings.hide_pins_on_capture:
            # 旧贴图不该被截进新图里;截图结束(含取消/失败)后恢复。
            self._pins_hidden_for_capture = [
                pin for pin in self.pin_windows if pin.isVisible()
            ]
            for pin in self._pins_hidden_for_capture:
                pin.hide()
        QTimer.singleShot(160, lambda: self._begin_capture(action, fullscreen))

    def _begin_capture(self, action: str, fullscreen: bool = False) -> None:
        # processEvents 期间热键事件可能重入 request_capture;保持
        # _capture_pending=True 直到遮罩就位,堵住这个重入窗口。
        try:
            if self.overlay is not None:
                return
            self.app.processEvents()
            desktop = capture_virtual_desktop()
            overlay = CaptureOverlay(desktop, action, quick_preview=True)
            self.overlay = overlay
            overlay.completed.connect(self._capture_completed)
            overlay.session_requested.connect(self._capture_session_requested)
            overlay.ocr_ready.connect(
                lambda image, current=overlay: self._recognize_image(image, current)
            )
            overlay.cancelled.connect(self._capture_cancelled)
            overlay.start()
            if fullscreen:
                overlay.select_all()
        except Exception as exc:
            self.overlay = None
            self._restore_settings_dialog()
            self.notify("截图失败", str(exc), warning=True)
        finally:
            self._capture_pending = False

    def _restore_settings_dialog(self) -> None:
        """截图临时隐藏了设置窗口的话,把它连同未保存的编辑一起还回来。"""
        self._restore_hidden_pins()
        if not self._settings_was_visible:
            return
        self._settings_was_visible = False
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def show_about(self) -> None:
        QMessageBox.about(
            None,
            f"关于 {APP_TITLE}",
            f"{APP_TITLE}\n\n"
            f"版本：v{__version__}\n"
            f"项目地址：{PROJECT_URL}\n"
            f"作者：{AUTHOR}",
        )

    def _restore_hidden_pins(self) -> None:
        hidden = self._pins_hidden_for_capture
        self._pins_hidden_for_capture = []
        for pin in hidden:
            # 隐藏期间可能被"关闭所有贴图"关掉了,只恢复仍存活的。
            if pin in self.pin_windows:
                pin.show()

    def _capture_completed(self, image, action: str, global_pos) -> None:  # type: ignore[no-untyped-def]
        self.overlay = None
        self._last_image = image
        self._restore_settings_dialog()
        if action == "copy":
            try:
                self.app.clipboard().setImage(image)
                self.notify(
                    "截图成功",
                    "已复制到剪贴板，可以直接粘贴到聊天软件。"
                    "需要留档可在托盘菜单点“保存最近一张截图”。",
                )
            except Exception as exc:
                self.notify("复制失败", str(exc), warning=True)
            return
        if action == "pin":
            self._create_pin_window(image, global_pos)
            return
        if action == "save_as":
            self._save_image_as(image, clipboard_on_cancel=True)
            return
        if action == "ocr":
            # 识别已由 ocr_ready 信号携带干净图触发;这里只做记账:
            # _last_image 保存的是带完整标注的图,托盘"保存最近一张"不丢标注。
            return
        self._save_image(image)

    def _capture_session_requested(
        self,
        image: QImage,
        desktop: CapturedDesktop,
        selection: QRectF,
        action: str,
    ) -> None:
        del selection
        self.overlay = None
        self._restore_settings_dialog()
        self._create_capture_session(image, desktop, action)

    def _create_capture_session(
        self, image: QImage, desktop: CapturedDesktop, action: str
    ) -> None:
        session = CaptureSessionWindow(image, action)
        session.closed.connect(self._capture_session_closed)
        session.completed.connect(
            lambda result, resolved, current=session: self._complete_capture_session(
                current, result, resolved
            )
        )
        session.reselect_requested.connect(
            lambda current=session, snapshot=desktop, current_action=action: self._reselect_capture_session(
                current, snapshot, current_action
            )
        )
        session.ocr_requested.connect(
            lambda source, current=session: self._recognize_image(source, current)
        )
        self.capture_sessions.append(session)
        session.show()
        session.raise_()
        session.activateWindow()

    def _complete_capture_session(
        self, session: CaptureSessionWindow, image: QImage, action: str
    ) -> None:
        if session not in self.capture_sessions:
            return
        self._last_image = image
        if action == "copy":
            self.app.clipboard().setImage(image)
        elif action == "save":
            if not self._save_image(image):
                return
        session.close()

    def _reselect_capture_session(
        self,
        session: CaptureSessionWindow,
        desktop: CapturedDesktop,
        action: str,
    ) -> None:
        if session not in self.capture_sessions or self.overlay is not None:
            return
        session.close()
        overlay = CaptureOverlay(desktop, action, quick_preview=True)
        self.overlay = overlay
        overlay.completed.connect(self._capture_completed)
        overlay.session_requested.connect(self._capture_session_requested)
        overlay.ocr_ready.connect(
            lambda source, current=overlay: self._recognize_image(source, current)
        )
        overlay.cancelled.connect(self._capture_cancelled)
        overlay.start()

    def _capture_session_closed(self, session: object) -> None:
        self.capture_sessions = [
            current for current in self.capture_sessions if current is not session
        ]

    def _ensure_ocr_executor(self) -> ProcessPoolExecutor:
        if self._ocr_executor is None:
            self._ocr_executor = ProcessPoolExecutor(
                max_workers=1,
                mp_context=multiprocessing.get_context("spawn"),
            )
        return self._ocr_executor

    def _reset_ocr_executor(self) -> None:
        executor = self._ocr_executor
        self._ocr_executor = None
        self._ocr_process_ready = False
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def _release_idle_ocr_process(self) -> None:
        if self._ocr_busy:
            self._ocr_idle_timer.start()
            return
        self._reset_ocr_executor()

    @staticmethod
    def _image_png_bytes(image: QImage) -> bytes:
        data = QByteArray()
        buffer = QBuffer(data)
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            raise RuntimeError("无法准备待识别图片")
        try:
            if not image.save(buffer, "PNG"):
                raise RuntimeError("无法编码待识别图片")
        finally:
            buffer.close()
        return bytes(data)

    def _recognize_image(
        self,
        image: QImage,
        target: CaptureOverlay | PinWindow | CaptureSessionWindow | None = None,
    ) -> None:
        """在隔离进程跑 OCR,完成后回主线程更新原图文字层。

        大图密集文字识别可达数秒;原生 DLL 崩溃也只损失工作进程。
        """
        if self._ocr_busy:
            if target is not None:
                target.set_ocr_error("已有识别任务正在运行,请稍后重试")
                self.notify("正在识别中", "已有识别任务正在运行，请稍后再试。")
                return
            self.notify(
                "正在识别中",
                "请稍候(首次使用需要加载识别引擎,会多花几秒)。",
            )
            return
        self._ocr_busy = True
        self._ocr_idle_timer.stop()
        self._ocr_target = target
        if not self._ocr_process_ready:
            # 托盘应用没有可见窗口,WaitCursor 用户看不到;
            # 冷启动要几秒,不提示会被当成"按了没反应"。
            self.notify("正在识别", "首次识别需要加载引擎,请稍候几秒…")
        worker = _OcrWorker()
        worker.finished.connect(self._on_ocr_finished)
        worker.failed.connect(self._on_ocr_failed)
        self._ocr_worker = worker  # 线程结束前必须持有引用,防 GC
        try:
            payload = self._image_png_bytes(image)
            future = self._ensure_ocr_executor().submit(
                ocr.recognize_png_bytes, payload
            )
        except Exception as exc:
            worker.failed.emit(str(exc) or "无法启动识别进程")
            return

        def done(completed: Future) -> None:
            try:
                outcome = completed.result()
            except BrokenProcessPool:
                # 原生库崩溃无法由 Python 捕获；熔断本次会话里的 RapidOCR，
                # 下一次识别自动走 Windows OCR，避免用户连续触发同一崩溃。
                os.environ[ocr.SAFE_MODE_ENV] = "1"
                worker.failed.emit(
                    "内置识别进程异常退出，已自动切换系统安全模式，请重试。"
                )
            except Exception as exc:
                worker.failed.emit(
                    str(exc) or "识别进程异常退出,请重试"
                )
            else:
                worker.finished.emit(outcome)

        future.add_done_callback(done)

    def _finish_ocr_request(self) -> None:
        self._ocr_busy = False
        self._ocr_worker = None
        self._ocr_idle_timer.start()

    def _on_ocr_failed(self, message: str) -> None:
        target = self._ocr_target
        self._ocr_target = None
        # 推理异常可能来自原生进程崩溃;统一丢弃工作进程,下次自动重建。
        self._reset_ocr_executor()
        self._finish_ocr_request()
        if target is not None and target is self.overlay:
            target.set_ocr_error(message)
            self.notify("识别失败", message, warning=True)
            return
        if isinstance(target, PinWindow) and target in self.pin_windows:
            target.set_ocr_error(message)
            self.notify("识别失败", message, warning=True)
            return
        if isinstance(target, CaptureSessionWindow) and target in self.capture_sessions:
            target.set_ocr_error(message)
            self.notify("识别失败", message, warning=True)
            return
        self.notify("识别失败", message, warning=True)

    def _on_ocr_finished(self, outcome: ocr.OcrOutcome) -> None:
        target = self._ocr_target
        self._ocr_target = None
        self._ocr_process_ready = True
        self._finish_ocr_request()
        if target is not None:
            if target is self.overlay:
                target.set_ocr_result(outcome)
            elif isinstance(target, PinWindow) and target in self.pin_windows:
                target.set_ocr_result(outcome)
            elif (
                isinstance(target, CaptureSessionWindow)
                and target in self.capture_sessions
            ):
                target.set_ocr_result(outcome)
            if not outcome.text:
                self.notify(
                    "未识别到文字",
                    "图片里没有可识别的文字内容；可以放大图片后再试。",
                    warning=True,
                )
            return
        if not outcome.text:
            self.notify(
                "未识别到文字",
                "图片里没有可识别的文字内容;艺术字或过小的文字可能无法识别。",
                warning=True,
            )
            return
        self.app.clipboard().setText(outcome.text)
        self.notify("识别完成", "识别结果已复制到剪贴板。")

    def _save_image(self, image: QImage) -> bool:
        try:
            target = save_png_atomic(image, Path(self.settings.save_directory))
            self.notify(
                "截图已保存",
                f"{target}\n点击本通知打开所在文件夹。",
                saved_path=target,
            )
            return True
        except Exception as exc:
            # 保存失败时把图塞进剪贴板兜底,截图内容不至于直接丢失。
            try:
                self.app.clipboard().setImage(image)
                fallback = "截图已复制到剪贴板，请尽快粘贴保存。"
            except Exception:
                fallback = ""
            self.notify(
                "保存失败",
                f"无法写入截图文件：{exc}\n{fallback}".rstrip(),
                warning=True,
            )
            return False

    def _create_pin_window(
        self, image: QImage, global_pos, fit_to_screen: bool = False
    ) -> None:
        logical = image.deviceIndependentSize()
        position = global_pos if isinstance(global_pos, QPoint) else QPoint(0, 0)
        pin = PinWindow(
            image,
            QSize(max(1, round(logical.width())), max(1, round(logical.height()))),
            position,
        )
        pin.closed.connect(self._pin_closed)
        pin.save_requested.connect(
            lambda saved, pin=pin: self._save_pin_image(pin, saved)
        )
        pin.ocr_requested.connect(
            lambda image, current=pin: self._recognize_image(image, current)
        )
        pin.save_as_requested.connect(
            lambda saved, pin=pin: self._save_pin_image_as(pin, saved)
        )
        pin.close_all_requested.connect(self.close_all_pins)
        self.pin_windows.append(pin)
        pin.show()
        pin.raise_()
        # 仅剪贴板来源做适配:截图钉住必须原位 1:1 覆盖,不能缩放。
        if not fit_to_screen:
            return
        screen = QGuiApplication.screenAt(position) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        fit = min(
            1.0,
            available.width() * 0.9 / max(1.0, logical.width()),
            available.height() * 0.9 / max(1.0, logical.height()),
        )
        if fit < 1.0:
            pin.fit_to(fit)
        # 从托盘菜单触发时光标在屏幕角落,窗口会滑出屏;整体钳回可视区。
        geometry = pin.geometry()
        x = max(
            available.left(),
            min(geometry.x(), available.right() - geometry.width() + 1),
        )
        y = max(
            available.top(),
            min(geometry.y(), available.bottom() - geometry.height() + 1),
        )
        pin.move(x, y)

    def _save_pin_image(self, pin: PinWindow, image: QImage) -> None:
        # 贴图窗口内保存也要有即时反馈,与 Ctrl+C 的"已复制"一致。
        pin.show_save_result(self._save_image(image))

    def _save_pin_image_as(self, pin: PinWindow, image: QImage) -> None:
        result = self._save_image_as(image, clipboard_on_cancel=False)
        # 对话框打开期间贴图可能被 Esc/托盘关闭;只对仍存活的贴图反馈,
        # 访问已销毁的 QWidget 会抛 RuntimeError 甚至崩溃。
        if result is not None and pin in self.pin_windows:
            pin.show_save_result(result)

    def _save_image_as(
        self, image: QImage, clipboard_on_cancel: bool
    ) -> bool | None:
        """弹文件对话框另存;返回 True/False 表示保存结果,None 表示取消。"""
        start_dir = self._last_save_as_dir or Path(self.settings.save_directory)
        try:
            start_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            start_dir = Path.home()
        suggested = unique_screenshot_path(start_dir)
        # 对话框存续期间:1) 借用 _capture_pending 挡住全局热键重入,
        # 否则新遮罩会盖住模态对话框把界面锁死;2) 临时藏起置顶贴图,
        # 否则无父的原生对话框会被压在贴图后面点不到。
        self._capture_pending = True
        visible_pins = [pin for pin in self.pin_windows if pin.isVisible()]
        for pin in visible_pins:
            pin.hide()
        try:
            filename, _selected_filter = QFileDialog.getSaveFileName(
                None,
                "另存截图",
                str(suggested),
                "PNG 图片 (*.png)",
            )
        finally:
            self._capture_pending = False
            for pin in visible_pins:
                if pin in self.pin_windows:
                    pin.show()
        if not filename:
            if clipboard_on_cancel:
                # 截图遮罩已经关闭,图不落盘就丢了;塞进剪贴板兜底。
                self.app.clipboard().setImage(image)
                self.notify("另存已取消", "截图已复制到剪贴板，可直接粘贴使用。")
            return None
        target = Path(filename)
        if target.suffix.lower() != ".png":
            # 追加而不是 with_suffix 替换:"shot.v2" 应变成 "shot.v2.png",
            # 不能把点分段吃掉后静默指向另一个文件。
            target = target.with_name(target.name + ".png")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not image.save(str(target), "PNG"):
                raise OSError("图片编码失败")
        except Exception as exc:
            try:
                self.app.clipboard().setImage(image)
                fallback = "截图已复制到剪贴板，请尽快粘贴保存。"
            except Exception:
                fallback = ""
            self.notify(
                "另存失败",
                f"无法写入 {target}：{exc}\n{fallback}".rstrip(),
                warning=True,
            )
            return False
        self._last_save_as_dir = target.parent
        self.notify(
            "截图已保存",
            f"{target}\n点击本通知打开所在文件夹。",
            saved_path=target,
        )
        return True

    def _pin_closed(self, pin: object) -> None:
        self.pin_windows = [
            window for window in self.pin_windows if window is not pin
        ]

    def close_all_pins(self) -> None:
        for pin in list(self.pin_windows):
            pin.close()
        self.pin_windows.clear()

    def open_save_directory(self) -> None:
        directory = Path(self.settings.save_directory).expanduser()
        try:
            directory.mkdir(parents=True, exist_ok=True)
            os.startfile(str(directory))  # type: ignore[attr-defined]
        except OSError as exc:
            self.notify("无法打开文件夹", str(exc), warning=True)

    def _notification_clicked(self) -> None:
        target = self._last_saved_path
        if target is None or not target.exists():
            return
        try:
            subprocess.Popen(["explorer", f"/select,{target}"])
        except OSError:
            pass

    def _capture_cancelled(self) -> None:
        self.overlay = None
        self._restore_settings_dialog()

    def _toggle_startup(self, checked: bool) -> None:
        candidate = self.settings.updated(start_with_windows=checked)
        notice = (
            "已开启开机启动，登录 Windows 后会自动运行。"
            if checked
            else "已关闭开机启动。"
        )
        success, message = self.apply_settings(candidate, notice=notice)
        if not success:
            self._sync_tray_state()
            self.notify("开机启动设置失败", message, warning=True)

    def _sync_tray_state(self) -> None:
        blocker = QSignalBlocker(self.startup_action)
        self.startup_action.setChecked(self.settings.start_with_windows)
        del blocker
        self.tray.setToolTip(
            f"{APP_TITLE}\n"
            f"{self.settings.copy_hotkey} 复制 · "
            f"{self.settings.save_hotkey} 保存 · "
            f"{self.settings.pin_hotkey} 钉住\n"
            "单击截图,双击打开设置"
        )

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._tray_click_timer.start()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._tray_click_timer.stop()
            self.show_settings()
        else:
            # 右键菜单/中键会先收到 Trigger 之外的事件;取消待发的单击
            # 截图,避免截到打开着的托盘菜单。
            self._tray_click_timer.stop()

    def _hotkey_summary(self) -> str:
        return (
            f"{self.settings.copy_hotkey} 复制；"
            f"{self.settings.save_hotkey} 保存；"
            f"{self.settings.pin_hotkey} 钉住。"
        )

    def _show_startup_notice(self) -> None:
        hotkey_text = self._hotkey_summary()
        if self._startup_warnings:
            details = "\n".join(self._startup_warnings)
            self.notify("截图工具已启动，但有设置需要处理", f"{hotkey_text}\n{details}", True)
        elif "--autostart" not in self.app.arguments():
            # 开机自启的实例不打扰用户;有警告时仍然要弹出来。
            self.notify("截图工具已启动", hotkey_text)

    def notify(
        self,
        title: str,
        message: str,
        warning: bool = False,
        saved_path: Path | None = None,
    ) -> None:
        # 普通通知不清掉保存路径:通知中心里那条"点击打开所在文件夹"
        # 可能还没被点,清了它就变成无声空操作。
        if saved_path is not None:
            self._last_saved_path = saved_path
        icon = (
            QSystemTrayIcon.MessageIcon.Warning
            if warning
            else QSystemTrayIcon.MessageIcon.Information
        )
        self.tray.showMessage(title, message, icon, 4500)

    def handle_second_instance(self) -> None:
        self.notify("截图工具正在运行", self._hotkey_summary())

    def quit(self) -> None:
        if self.overlay is not None:
            self.overlay.cancel()
            self.overlay = None
        self.close_all_pins()
        for session in list(self.capture_sessions):
            session.close()
        self.capture_sessions.clear()
        self.settings_dialog.close()
        self.app.quit()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._reset_ocr_executor()
        self.hotkeys.close()
        self.tray.hide()


def run() -> int:
    configure_diagnostics()
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "SimpleScreenshot.1"
        )
    except (AttributeError, OSError):
        pass

    app = ResilientApplication(sys.argv)
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
