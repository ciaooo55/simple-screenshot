from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any


APP_NAME = "SimpleScreenshot"
CONFIG_VERSION = 1


def application_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def default_config_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME
    return Path.home() / "AppData" / "Roaming" / APP_NAME


@dataclass(frozen=True, slots=True)
class AppSettings:
    version: int
    copy_hotkey: str
    save_hotkey: str
    save_directory: str
    start_with_windows: bool

    def updated(self, **changes: Any) -> "AppSettings":
        return replace(self, **changes)


def default_settings(base_dir: Path | None = None) -> AppSettings:
    root = (base_dir or application_base_dir()).resolve()
    return AppSettings(
        version=CONFIG_VERSION,
        copy_hotkey="Alt+A",
        save_hotkey="Alt+S",
        save_directory=str(root / "tp"),
        start_with_windows=False,
    )


class SettingsStore:
    def __init__(
        self,
        config_dir: Path | None = None,
        base_dir: Path | None = None,
    ) -> None:
        self.config_dir = (config_dir or default_config_dir()).resolve()
        self.path = self.config_dir / "settings.json"
        self.error_log_path = self.config_dir / "settings.error.log"
        self.base_dir = (base_dir or application_base_dir()).resolve()
        self.last_warning: str | None = None

    def load(self) -> AppSettings:
        defaults = default_settings(self.base_dir)
        self.last_warning = None
        if not self.path.exists():
            return defaults

        try:
            with self.path.open("r", encoding="utf-8") as stream:
                raw = json.load(stream)
            return self._decode(raw, defaults)
        except Exception as exc:  # Config errors must never prevent startup.
            self.last_warning = f"设置文件读取失败，已使用默认设置：{exc}"
            self._record_error(self.last_warning)
            return defaults

    def save(self, settings: AppSettings) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        payload = asdict(settings.updated(version=CONFIG_VERSION))
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _decode(raw: Any, defaults: AppSettings) -> AppSettings:
        if not isinstance(raw, dict):
            raise ValueError("设置文件根节点不是对象")
        version = raw.get("version", CONFIG_VERSION)
        if version != CONFIG_VERSION:
            raise ValueError(f"不支持的设置版本：{version}")

        copy_hotkey = raw.get("copy_hotkey", defaults.copy_hotkey)
        save_hotkey = raw.get("save_hotkey", defaults.save_hotkey)
        save_directory = raw.get("save_directory", defaults.save_directory)
        start_with_windows = raw.get(
            "start_with_windows", defaults.start_with_windows
        )

        if not isinstance(copy_hotkey, str) or not copy_hotkey.strip():
            raise ValueError("复制快捷键无效")
        if not isinstance(save_hotkey, str) or not save_hotkey.strip():
            raise ValueError("保存快捷键无效")
        if not isinstance(save_directory, str) or not save_directory.strip():
            raise ValueError("保存目录无效")
        if not isinstance(start_with_windows, bool):
            raise ValueError("开机启动设置无效")

        # Keep validation close to persistence so malformed manual edits are
        # diagnosed and safely replaced by defaults on the next launch.
        from .hotkeys import parse_hotkey

        copy_parsed = parse_hotkey(copy_hotkey)
        save_parsed = parse_hotkey(save_hotkey)
        if copy_parsed == save_parsed:
            raise ValueError("复制和保存快捷键不能相同")

        return AppSettings(
            version=CONFIG_VERSION,
            copy_hotkey=copy_parsed.display,
            save_hotkey=save_parsed.display,
            save_directory=save_directory.strip(),
            start_with_windows=start_with_windows,
        )

    def _record_error(self, message: str) -> None:
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().isoformat(timespec="seconds")
            with self.error_log_path.open("a", encoding="utf-8") as stream:
                stream.write(f"[{timestamp}] {message}\n")
        except OSError:
            pass
