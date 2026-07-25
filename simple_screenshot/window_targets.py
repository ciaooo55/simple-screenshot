from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from typing import Sequence

from PySide6.QtCore import QRect, QRectF
from PySide6.QtGui import QGuiApplication, QScreen


@dataclass(frozen=True, slots=True)
class WindowTarget:
    rect: QRectF
    title: str = ""


def discover_window_targets(
    virtual_geometry: QRect,
    screens: Sequence[QScreen] | None = None,
) -> list[WindowTarget]:
    """Return visible top-level windows in front-to-back z-order.

    Win32 reports physical desktop coordinates while Qt mouse events use
    device-independent coordinates. Each rectangle is therefore converted
    using the monitor that owns the window, then translated into overlay-local
    coordinates.
    """

    if sys.platform != "win32":
        return []

    from ctypes import wintypes

    user32 = ctypes.windll.user32
    try:
        dwmapi = ctypes.windll.dwmapi
    except OSError:
        dwmapi = None

    class WinRect(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    class MonitorInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", WinRect),
            ("rcWork", WinRect),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        ]

    enum_proc_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HWND,
        wintypes.LPARAM,
    )
    user32.EnumWindows.argtypes = [enum_proc_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [
        wintypes.HWND,
        wintypes.LPWSTR,
        ctypes.c_int,
    ]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(WinRect)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = [
        wintypes.HMONITOR,
        ctypes.POINTER(MonitorInfo),
    ]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    if dwmapi is not None:
        dwmapi.DwmGetWindowAttribute.argtypes = [
            wintypes.HWND,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        dwmapi.DwmGetWindowAttribute.restype = wintypes.LONG

    qt_screens = list(screens or QGuiApplication.screens())
    screens_by_name = {screen.name().casefold(): screen for screen in qt_screens}
    overlay_bounds = QRectF(
        0.0,
        0.0,
        float(virtual_geometry.width()),
        float(virtual_geometry.height()),
    )
    current_pid = os.getpid()
    targets: list[WindowTarget] = []
    seen_rects: set[tuple[int, int, int, int]] = set()

    def window_rect(hwnd: int) -> WinRect | None:
        rect = WinRect()
        if dwmapi is not None:
            result = dwmapi.DwmGetWindowAttribute(
                hwnd,
                9,  # DWMWA_EXTENDED_FRAME_BOUNDS
                ctypes.byref(rect),
                ctypes.sizeof(rect),
            )
            if result == 0:
                return rect
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return rect
        return None

    def is_cloaked(hwnd: int) -> bool:
        if dwmapi is None:
            return False
        cloaked = wintypes.DWORD()
        result = dwmapi.DwmGetWindowAttribute(
            hwnd,
            14,  # DWMWA_CLOAKED
            ctypes.byref(cloaked),
            ctypes.sizeof(cloaked),
        )
        return result == 0 and bool(cloaked.value)

    def monitor_mapping(hwnd: int) -> tuple[QRect, WinRect, float] | None:
        monitor = user32.MonitorFromWindow(hwnd, 2)  # nearest monitor
        if not monitor:
            return None
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        screen = screens_by_name.get(str(info.szDevice).casefold())
        if screen is None:
            native_width = info.rcMonitor.right - info.rcMonitor.left
            native_height = info.rcMonitor.bottom - info.rcMonitor.top
            wants_primary = bool(info.dwFlags & 1)

            def match_score(candidate: QScreen) -> float:
                geometry = candidate.geometry()
                scale = max(1.0, float(candidate.devicePixelRatio()))
                primary_penalty = (
                    0.0
                    if (candidate is QGuiApplication.primaryScreen()) == wants_primary
                    else 1_000_000.0
                )
                size_error = abs(native_width / scale - geometry.width()) + abs(
                    native_height / scale - geometry.height()
                )
                position_error = abs(
                    info.rcMonitor.left / scale - geometry.x()
                ) + abs(info.rcMonitor.top / scale - geometry.y())
                return primary_penalty + size_error * 10 + position_error

            if not qt_screens:
                return None
            screen = min(qt_screens, key=match_score)
        return screen.geometry(), info.rcMonitor, max(
            1.0,
            float(screen.devicePixelRatio()),
        )

    def callback(hwnd, _lparam):  # type: ignore[no-untyped-def]
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        if is_cloaked(hwnd):
            return True

        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value == current_pid:
            return True

        title_length = user32.GetWindowTextLengthW(hwnd)
        if title_length <= 0:
            return True
        title_buffer = ctypes.create_unicode_buffer(title_length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, title_length + 1)
        title = title_buffer.value.strip()
        if not title:
            return True

        rect = window_rect(hwnd)
        mapping = monitor_mapping(hwnd)
        if rect is None or mapping is None:
            return True
        screen_geometry, native_monitor, scale = mapping
        logical = QRectF(
            screen_geometry.x()
            + (rect.left - native_monitor.left) / scale
            - virtual_geometry.x(),
            screen_geometry.y()
            + (rect.top - native_monitor.top) / scale
            - virtual_geometry.y(),
            (rect.right - rect.left) / scale,
            (rect.bottom - rect.top) / scale,
        ).intersected(overlay_bounds)
        if logical.width() < 24 or logical.height() < 24:
            return True

        key = (
            round(logical.x()),
            round(logical.y()),
            round(logical.width()),
            round(logical.height()),
        )
        if key not in seen_rects:
            seen_rects.add(key)
            targets.append(WindowTarget(logical, title))
        return True

    callback_ref = enum_proc_type(callback)
    user32.EnumWindows(callback_ref, 0)
    return targets
