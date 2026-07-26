from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QWidget


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

HOTKEY_IDS: dict[str, int] = {
    "copy": 0xB101,
    "save": 0xB102,
    "pin": 0xB103,
}
HOTKEY_ACTIONS: dict[int, str] = {
    identifier: action for action, identifier in HOTKEY_IDS.items()
}
ACTION_TITLES: dict[str, str] = {
    "copy": "截图并复制",
    "save": "截图并保存",
    "pin": "截图并钉住",
}

# 无修饰键时允许单独注册的按键:F1-F24 与 PrintScreen。
# 其余按键裸注册会在全系统范围劫持该键(比如裸 A 让所有程序打不出 a)。
_BARE_KEY_WHITELIST = set(range(0x70, 0x88)) | {0x2C}


def _validate_modifiers(modifiers: int, virtual_key: int) -> None:
    if modifiers == 0 and virtual_key not in _BARE_KEY_WHITELIST:
        raise ValueError(
            "单独的字母/数字等按键会屏蔽其他程序,请搭配 "
            "Ctrl/Alt/Shift/Win 使用(F1-F24、PrintScreen 可单独使用)"
        )


SPECIAL_KEYS: dict[str, int] = {
    "BACKSPACE": 0x08,
    "TAB": 0x09,
    "ENTER": 0x0D,
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "SPACE": 0x20,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
    "END": 0x23,
    "HOME": 0x24,
    "LEFT": 0x25,
    "UP": 0x26,
    "RIGHT": 0x27,
    "DOWN": 0x28,
    "PRINTSCREEN": 0x2C,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
}

DISPLAY_KEYS: dict[int, str] = {
    value: ("Esc" if key in {"ESC", "ESCAPE"} else key.title())
    for key, value in SPECIAL_KEYS.items()
}
DISPLAY_KEYS.update(
    {
        0x21: "PageUp",
        0x22: "PageDown",
        0x2C: "PrintScreen",
    }
)


@dataclass(frozen=True, slots=True)
class Hotkey:
    modifiers: int
    virtual_key: int
    key_name: str

    @property
    def display(self) -> str:
        parts: list[str] = []
        if self.modifiers & MOD_CONTROL:
            parts.append("Ctrl")
        if self.modifiers & MOD_ALT:
            parts.append("Alt")
        if self.modifiers & MOD_SHIFT:
            parts.append("Shift")
        if self.modifiers & MOD_WIN:
            parts.append("Win")
        parts.append(self.key_name)
        return "+".join(parts)


def parse_hotkey(value: str) -> Hotkey:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("快捷键不能为空")
    tokens = [token.strip() for token in value.split("+") if token.strip()]
    if not tokens:
        raise ValueError("快捷键不能为空")

    modifiers = 0
    key_token: str | None = None
    for token in tokens:
        normalized = token.upper()
        if normalized in {"CTRL", "CONTROL"}:
            modifiers |= MOD_CONTROL
        elif normalized == "ALT":
            modifiers |= MOD_ALT
        elif normalized == "SHIFT":
            modifiers |= MOD_SHIFT
        elif normalized in {"WIN", "WINDOWS", "META"}:
            modifiers |= MOD_WIN
        elif key_token is None:
            key_token = token
        else:
            raise ValueError("快捷键只能包含一个主键")

    if key_token is None:
        raise ValueError("请同时按下一个非修饰键")
    virtual_key, display_name = _parse_key_token(key_token)
    _validate_modifiers(modifiers, virtual_key)
    return Hotkey(modifiers, virtual_key, display_name)


def _parse_key_token(token: str) -> tuple[int, str]:
    normalized = token.upper().replace(" ", "")
    if len(normalized) == 1 and (normalized.isalpha() or normalized.isdigit()):
        return ord(normalized), normalized
    if normalized.startswith("F") and normalized[1:].isdigit():
        number = int(normalized[1:])
        if 1 <= number <= 24:
            return 0x6F + number, f"F{number}"
    if normalized in SPECIAL_KEYS:
        vk = SPECIAL_KEYS[normalized]
        return vk, DISPLAY_KEYS[vk]
    raise ValueError(f"不支持的主键：{token}")


def hotkey_from_key_event(event: QKeyEvent) -> Hotkey:
    key = event.key()
    modifier_keys = {
        Qt.Key.Key_Control,
        Qt.Key.Key_Shift,
        Qt.Key.Key_Alt,
        Qt.Key.Key_Meta,
    }
    if key in modifier_keys:
        raise ValueError("请同时按下一个非修饰键")

    modifiers = 0
    qt_modifiers = event.modifiers()
    if qt_modifiers & Qt.KeyboardModifier.ControlModifier:
        modifiers |= MOD_CONTROL
    if qt_modifiers & Qt.KeyboardModifier.AltModifier:
        modifiers |= MOD_ALT
    if qt_modifiers & Qt.KeyboardModifier.ShiftModifier:
        modifiers |= MOD_SHIFT
    if qt_modifiers & Qt.KeyboardModifier.MetaModifier:
        modifiers |= MOD_WIN

    native_key = int(event.nativeVirtualKey())
    if 0x41 <= native_key <= 0x5A or 0x30 <= native_key <= 0x39:
        name = chr(native_key)
    elif 0x70 <= native_key <= 0x87:
        name = f"F{native_key - 0x6F}"
    elif native_key in DISPLAY_KEYS:
        name = DISPLAY_KEYS[native_key]
    else:
        text = event.text().upper()
        if len(text) == 1 and (text.isalpha() or text.isdigit()):
            native_key = ord(text)
            name = text
        else:
            raise ValueError("这个按键暂不支持，请换一个快捷键")
    _validate_modifiers(modifiers, native_key)
    return Hotkey(modifiers, native_key, name)


class HotkeyBackendProtocol(Protocol):
    def register(self, identifier: int, hotkey: Hotkey) -> bool: ...

    def unregister(self, identifier: int) -> None: ...


class WindowsHotkeyBackend:
    def __init__(self, window_handle: int | None = None) -> None:
        self.window_handle = window_handle
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.RegisterHotKey.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            wintypes.UINT,
            wintypes.UINT,
        ]
        self.user32.RegisterHotKey.restype = wintypes.BOOL
        self.user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.UnregisterHotKey.restype = wintypes.BOOL

    def register(self, identifier: int, hotkey: Hotkey) -> bool:
        return bool(
            self.user32.RegisterHotKey(
                self.window_handle,
                identifier,
                hotkey.modifiers | MOD_NOREPEAT,
                hotkey.virtual_key,
            )
        )

    def unregister(self, identifier: int) -> None:
        self.user32.UnregisterHotKey(self.window_handle, identifier)


class NativeHotkeyWindow(QWidget):
    hotkey_pressed = Signal(int)

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.window_handle = int(self.winId())

    def nativeEvent(self, event_type: bytes, message: int) -> tuple[bool, int]:
        if event_type != b"windows_generic_MSG":
            return False, 0
        try:
            native_message = wintypes.MSG.from_address(int(message))
        except (TypeError, ValueError):
            return False, 0
        if native_message.message == WM_HOTKEY:
            self.hotkey_pressed.emit(int(native_message.wParam))
            return True, 0
        return False, 0


class HotkeyManager(QObject):
    activated = Signal(str)

    def __init__(
        self,
        backend: HotkeyBackendProtocol | None = None,
        install_filter: bool = True,
    ) -> None:
        super().__init__()
        self._native_window: NativeHotkeyWindow | None = None
        if backend is None:
            app = QApplication.instance()
            if install_filter and app is None:
                raise RuntimeError("必须先创建 QApplication")
            if install_filter:
                self._native_window = NativeHotkeyWindow()
                self._native_window.hotkey_pressed.connect(self._handle_identifier)
                backend = WindowsHotkeyBackend(self._native_window.window_handle)
            else:
                backend = WindowsHotkeyBackend()
        self.backend = backend
        self.current: dict[int, Hotkey] = {}
        self._suspended = False

    def suspend(self) -> None:
        """临时放开系统层拦截(录制新快捷键时用),映射保持不变。"""
        if self._suspended:
            return
        self._suspended = True
        for identifier in self.current:
            self.backend.unregister(identifier)

    def resume(self) -> None:
        if not self._suspended:
            return
        self._suspended = False
        for identifier, hotkey in self.current.items():
            self.backend.register(identifier, hotkey)

    def apply(self, hotkeys: dict[str, Hotkey]) -> tuple[bool, str]:
        # apply 之后注册状态以结果为准,挂起标记必须清掉。
        self._suspended = False
        unknown = set(hotkeys) - set(HOTKEY_IDS)
        if unknown:
            return False, f"未知的快捷键动作：{'、'.join(sorted(unknown))}"
        values = list(hotkeys.values())
        if len(values) != len(set(values)):
            return False, "多个动作不能使用相同的快捷键"

        previous = dict(self.current)
        self.unregister_all()
        requested = {
            HOTKEY_IDS[action]: hotkey for action, hotkey in hotkeys.items()
        }
        registered: list[int] = []
        failed: Hotkey | None = None
        failed_action: str | None = None
        for identifier, hotkey in requested.items():
            if not self.backend.register(identifier, hotkey):
                failed = hotkey
                failed_action = HOTKEY_ACTIONS.get(identifier)
                break
            registered.append(identifier)

        if failed is None:
            self.current = requested
            return True, ""

        for identifier in registered:
            self.backend.unregister(identifier)
        self.current = {}

        restore_failed = False
        for identifier, hotkey in previous.items():
            if self.backend.register(identifier, hotkey):
                self.current[identifier] = hotkey
            else:
                restore_failed = True
        title = ACTION_TITLES.get(failed_action or "", failed_action or "")
        prefix = f"「{title}」的" if title else ""
        message = f"{prefix}快捷键 {failed.display} 已被其他程序占用或被系统保留"
        if restore_failed:
            message += "；原快捷键恢复失败，请重新设置"
        return False, message

    def unregister_all(self) -> None:
        for identifier in tuple(self.current):
            self.backend.unregister(identifier)
        self.current.clear()

    def _handle_identifier(self, identifier: int) -> None:
        action = HOTKEY_ACTIONS.get(identifier)
        if action is not None:
            self.activated.emit(action)

    def close(self) -> None:
        self.unregister_all()
        if self._native_window is not None:
            self._native_window.close()
            self._native_window.deleteLater()
            self._native_window = None
