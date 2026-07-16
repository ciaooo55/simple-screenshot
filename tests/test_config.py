from __future__ import annotations

import json

from simple_screenshot.config import AppSettings, SettingsStore


def test_missing_config_uses_project_tp(tmp_path):
    base = tmp_path / "portable"
    store = SettingsStore(tmp_path / "config", base)

    settings = store.load()

    assert settings.copy_hotkey == "Alt+A"
    assert settings.save_hotkey == "Alt+S"
    assert settings.save_directory == str(base.resolve() / "tp")
    assert settings.start_with_windows is False
    assert store.last_warning is None


def test_settings_round_trip(tmp_path):
    store = SettingsStore(tmp_path / "config", tmp_path)
    expected = AppSettings(1, "Ctrl+Shift+A", "F8", str(tmp_path / "shots"), True)

    store.save(expected)
    actual = store.load()

    assert actual == expected
    assert json.loads(store.path.read_text(encoding="utf-8"))["version"] == 1


def test_corrupt_config_falls_back_and_records_diagnostic(tmp_path):
    store = SettingsStore(tmp_path / "config", tmp_path / "base")
    store.config_dir.mkdir(parents=True)
    store.path.write_text('{"copy_hotkey": "Alt"}', encoding="utf-8")

    settings = store.load()

    assert settings.copy_hotkey == "Alt+A"
    assert store.last_warning is not None
    assert "设置文件读取失败" in store.last_warning
    assert store.error_log_path.exists()
    assert "非修饰键" in store.error_log_path.read_text(encoding="utf-8")


def test_duplicate_hotkeys_are_treated_as_invalid_config(tmp_path):
    store = SettingsStore(tmp_path / "config", tmp_path)
    store.config_dir.mkdir(parents=True)
    store.path.write_text(
        json.dumps(
            {
                "version": 1,
                "copy_hotkey": "Alt+A",
                "save_hotkey": "Alt+A",
                "save_directory": str(tmp_path / "tp"),
                "start_with_windows": False,
            }
        ),
        encoding="utf-8",
    )

    settings = store.load()

    assert settings.save_hotkey == "Alt+S"
    assert store.last_warning is not None
