from __future__ import annotations

import json

from simple_screenshot.config import AppSettings, SettingsStore, default_settings


def test_missing_config_uses_project_tp(tmp_path):
    base = tmp_path / "portable"
    store = SettingsStore(tmp_path / "config", base)

    settings = store.load()

    assert settings.copy_hotkey == "Alt+A"
    assert settings.save_hotkey == "Alt+S"
    assert settings.pin_hotkey == "Alt+Q"
    assert settings.save_directory == str(base.resolve() / "tp")
    assert settings.start_with_windows is False
    assert store.last_warning is None


def test_settings_round_trip(tmp_path):
    store = SettingsStore(tmp_path / "config", tmp_path)
    expected = AppSettings(
        2, "Ctrl+Shift+A", "F8", "F9", str(tmp_path / "shots"), True
    )

    store.save(expected)
    actual = store.load()

    assert actual == expected
    assert json.loads(store.path.read_text(encoding="utf-8"))["version"] == 2


def test_v1_config_migrates_with_default_pin_hotkey(tmp_path):
    store = SettingsStore(tmp_path / "config", tmp_path)
    store.config_dir.mkdir(parents=True)
    store.path.write_text(
        json.dumps(
            {
                "version": 1,
                "copy_hotkey": "Alt+A",
                "save_hotkey": "Alt+S",
                "save_directory": str(tmp_path / "tp"),
                "start_with_windows": True,
            }
        ),
        encoding="utf-8",
    )

    settings = store.load()

    assert settings.version == 2
    assert settings.copy_hotkey == "Alt+A"
    assert settings.save_hotkey == "Alt+S"
    assert settings.pin_hotkey == "Alt+Q"
    assert settings.start_with_windows is True
    assert store.last_warning is None


def test_v1_migration_avoids_pin_hotkey_collision(tmp_path):
    store = SettingsStore(tmp_path / "config", tmp_path)
    store.config_dir.mkdir(parents=True)
    store.path.write_text(
        json.dumps(
            {
                "version": 1,
                "copy_hotkey": "Alt+Q",
                "save_hotkey": "Alt+S",
                "save_directory": str(tmp_path / "tp"),
                "start_with_windows": False,
            }
        ),
        encoding="utf-8",
    )

    settings = store.load()

    assert settings.copy_hotkey == "Alt+Q"
    assert settings.pin_hotkey == "Alt+W"
    assert store.last_warning is None


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
                "version": 2,
                "copy_hotkey": "Alt+A",
                "save_hotkey": "Alt+A",
                "pin_hotkey": "Alt+Q",
                "save_directory": str(tmp_path / "tp"),
                "start_with_windows": False,
            }
        ),
        encoding="utf-8",
    )

    settings = store.load()

    assert settings.save_hotkey == "Alt+S"
    assert store.last_warning is not None


def test_duplicate_pin_hotkey_is_treated_as_invalid_config(tmp_path):
    store = SettingsStore(tmp_path / "config", tmp_path)
    store.config_dir.mkdir(parents=True)
    store.path.write_text(
        json.dumps(
            {
                "version": 2,
                "copy_hotkey": "Alt+A",
                "save_hotkey": "Alt+S",
                "pin_hotkey": "Alt+A",
                "save_directory": str(tmp_path / "tp"),
                "start_with_windows": False,
            }
        ),
        encoding="utf-8",
    )

    settings = store.load()

    assert settings.pin_hotkey == "Alt+Q"
    assert store.last_warning is not None


def test_hide_pins_on_capture_roundtrip_and_default(tmp_path):
    store = SettingsStore(config_dir=tmp_path / "cfg", base_dir=tmp_path)

    # 磁盘上真实存在的旧版配置缺这个键:走 _decode 迁移路径,默认打开。
    store.config_dir.mkdir(parents=True)
    store.path.write_text(
        json.dumps(
            {
                "version": 2,
                "copy_hotkey": "Alt+A",
                "save_hotkey": "Alt+S",
                "pin_hotkey": "Alt+Q",
                "save_directory": str(tmp_path / "tp"),
                "start_with_windows": False,
            }
        ),
        encoding="utf-8",
    )
    loaded = store.load()
    assert loaded.hide_pins_on_capture is True
    assert store.last_warning is None

    store.save(default_settings(tmp_path).updated(hide_pins_on_capture=False))
    assert store.load().hide_pins_on_capture is False


def test_hide_pins_wrong_type_falls_back_to_defaults(tmp_path):
    store = SettingsStore(config_dir=tmp_path / "cfg", base_dir=tmp_path)
    store.config_dir.mkdir(parents=True)
    store.path.write_text(
        json.dumps(
            {
                "version": 2,
                "copy_hotkey": "Alt+A",
                "save_hotkey": "Alt+S",
                "pin_hotkey": "Alt+Q",
                "save_directory": str(tmp_path / "tp"),
                "start_with_windows": False,
                "hide_pins_on_capture": 1,
            }
        ),
        encoding="utf-8",
    )

    loaded = store.load()
    assert loaded.hide_pins_on_capture is True
    assert store.last_warning is not None
