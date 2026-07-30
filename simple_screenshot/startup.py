from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import winreg


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_APPROVED_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
)
VALUE_NAME = "SimpleScreenshot"
ENABLED_STATE = bytes([0x02]) + bytes(11)


def startup_command() -> str:
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        return subprocess.list2cmdline([str(executable), "--autostart"])

    python_executable = Path(sys.executable).resolve()
    pythonw = python_executable.with_name("pythonw.exe")
    if pythonw.exists():
        python_executable = pythonw
    main_script = Path(__file__).resolve().parent.parent / "main.py"
    return subprocess.list2cmdline(
        [str(python_executable), str(main_script), "--autostart"]
    )


def set_start_with_windows(enabled: bool) -> None:
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        RUN_KEY,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        if enabled:
            winreg.SetValueEx(
                key,
                VALUE_NAME,
                0,
                winreg.REG_SZ,
                startup_command(),
            )
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass

    # Windows 10/11 还会读取 StartupApproved；Run 项存在但这里处于
    # 非 0x02 状态时，任务管理器会静默跳过启动。用户在应用内明确
    # 开启时同步修复该状态，关闭时一起清理，避免菜单与系统实际不一致。
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        STARTUP_APPROVED_KEY,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        if enabled:
            winreg.SetValueEx(
                key,
                VALUE_NAME,
                0,
                winreg.REG_BINARY,
                ENABLED_STATE,
            )
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass


def is_start_with_windows_enabled() -> bool:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_QUERY_VALUE,
        ) as key:
            value, value_type = winreg.QueryValueEx(key, VALUE_NAME)
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            STARTUP_APPROVED_KEY,
            0,
            winreg.KEY_QUERY_VALUE,
        ) as key:
            approved, approved_type = winreg.QueryValueEx(key, VALUE_NAME)
        return (
            value_type == winreg.REG_SZ
            and value == startup_command()
            and approved_type == winreg.REG_BINARY
            and bytes(approved)[:1] == b"\x02"
        )
    except OSError:
        return False
