from __future__ import annotations

import pytest

from simple_screenshot.hotkeys import (
    HOTKEY_IDS,
    Hotkey,
    HotkeyManager,
    parse_hotkey,
)


class FakeBackend:
    def __init__(self) -> None:
        self.registered: dict[int, Hotkey] = {}
        self.fail: set[Hotkey] = set()
        self.calls: list[tuple[str, int, Hotkey | None]] = []

    def register(self, identifier: int, hotkey: Hotkey) -> bool:
        self.calls.append(("register", identifier, hotkey))
        if hotkey in self.fail:
            return False
        self.registered[identifier] = hotkey
        return True

    def unregister(self, identifier: int) -> None:
        self.calls.append(("unregister", identifier, None))
        self.registered.pop(identifier, None)


def test_parse_and_normalize_hotkey():
    hotkey = parse_hotkey("shift+ctrl+f12")

    assert hotkey.display == "Ctrl+Shift+F12"
    assert hotkey.virtual_key == 0x7B


@pytest.mark.parametrize("value", ["", "Alt", "Ctrl+Shift", "Ctrl+A+B", "Alt+?"])
def test_invalid_hotkey_is_rejected(value):
    with pytest.raises(ValueError):
        parse_hotkey(value)


@pytest.mark.parametrize("value", ["A", "7", "Space", "Enter", "Left"])
def test_bare_key_without_modifier_is_rejected(value):
    # 裸键会被 RegisterHotKey 全局拦截,导致其他程序收不到该按键。
    with pytest.raises(ValueError):
        parse_hotkey(value)


@pytest.mark.parametrize("value", ["F5", "F12", "PrintScreen"])
def test_function_keys_may_be_registered_alone(value):
    hotkey = parse_hotkey(value)

    assert hotkey.modifiers == 0


def test_apply_registers_all_hotkeys():
    backend = FakeBackend()
    manager = HotkeyManager(backend, install_filter=False)
    mapping = {
        "copy": parse_hotkey("Alt+A"),
        "save": parse_hotkey("Alt+S"),
        "pin": parse_hotkey("Alt+Q"),
    }

    success, message = manager.apply(mapping)

    assert success is True
    assert message == ""
    assert backend.registered == {
        HOTKEY_IDS["copy"]: mapping["copy"],
        HOTKEY_IDS["save"]: mapping["save"],
        HOTKEY_IDS["pin"]: mapping["pin"],
    }


def test_apply_supports_partial_mapping():
    backend = FakeBackend()
    manager = HotkeyManager(backend, install_filter=False)
    mapping = {
        "copy": parse_hotkey("Alt+A"),
        "save": parse_hotkey("Alt+S"),
    }

    success, _ = manager.apply(mapping)

    assert success is True
    assert set(backend.registered) == {HOTKEY_IDS["copy"], HOTKEY_IDS["save"]}


def test_failed_new_registration_restores_previous_mapping():
    backend = FakeBackend()
    manager = HotkeyManager(backend, install_filter=False)
    old_mapping = {
        "copy": parse_hotkey("Alt+A"),
        "save": parse_hotkey("Alt+S"),
        "pin": parse_hotkey("Alt+Q"),
    }
    assert manager.apply(old_mapping)[0]

    new_mapping = {
        "copy": parse_hotkey("Ctrl+F7"),
        "save": parse_hotkey("Ctrl+F8"),
        "pin": parse_hotkey("Ctrl+F9"),
    }
    backend.fail.add(new_mapping["save"])
    success, message = manager.apply(new_mapping)

    assert success is False
    assert "Ctrl+F8" in message
    assert "截图并保存" in message
    assert backend.registered == {
        HOTKEY_IDS["copy"]: old_mapping["copy"],
        HOTKEY_IDS["save"]: old_mapping["save"],
        HOTKEY_IDS["pin"]: old_mapping["pin"],
    }
    assert manager.current == backend.registered


def test_duplicate_hotkeys_are_rejected_without_touching_backend():
    backend = FakeBackend()
    manager = HotkeyManager(backend, install_filter=False)
    hotkey = parse_hotkey("Alt+A")
    mapping = {
        "copy": hotkey,
        "save": hotkey,
        "pin": parse_hotkey("Alt+Q"),
    }

    success, message = manager.apply(mapping)

    assert success is False
    assert "相同" in message
    assert backend.calls == []


def test_unknown_action_is_rejected():
    backend = FakeBackend()
    manager = HotkeyManager(backend, install_filter=False)

    success, message = manager.apply({"bogus": parse_hotkey("Alt+A")})

    assert success is False
    assert "未知" in message
    assert backend.calls == []


def test_suspend_releases_keys_and_resume_restores_them():
    backend = FakeBackend()
    manager = HotkeyManager(backend, install_filter=False)
    mapping = {
        "copy": parse_hotkey("Alt+A"),
        "save": parse_hotkey("Alt+S"),
        "pin": parse_hotkey("Alt+Q"),
    }
    assert manager.apply(mapping)[0]

    manager.suspend()
    assert backend.registered == {}
    assert len(manager.current) == 3
    manager.suspend()  # 幂等:重复挂起不再动 backend
    assert backend.registered == {}

    manager.resume()
    assert set(backend.registered.values()) == set(mapping.values())
    calls_after = len(backend.calls)
    manager.resume()  # 幂等:未挂起时恢复不重复注册
    assert len(backend.calls) == calls_after


def test_apply_during_suspend_takes_over_cleanly():
    backend = FakeBackend()
    manager = HotkeyManager(backend, install_filter=False)
    mapping = {
        "copy": parse_hotkey("Alt+A"),
        "save": parse_hotkey("Alt+S"),
    }
    assert manager.apply(mapping)[0]
    manager.suspend()

    new_mapping = {
        "copy": parse_hotkey("Ctrl+F1"),
        "save": parse_hotkey("Ctrl+F2"),
    }
    assert manager.apply(new_mapping)[0]
    assert set(backend.registered.values()) == set(new_mapping.values())

    # apply 已清除挂起标记,resume 不应重复注册。
    calls_after = len(backend.calls)
    manager.resume()
    assert len(backend.calls) == calls_after


def test_incremental_fallback_keeps_unconflicted_hotkeys():
    # 模拟启动兜底:save 键被其他程序占用时,copy/pin 必须保住。
    backend = FakeBackend()
    manager = HotkeyManager(backend, install_filter=False)
    mapping = {
        "copy": parse_hotkey("Alt+A"),
        "save": parse_hotkey("Alt+S"),
        "pin": parse_hotkey("Alt+Q"),
    }
    backend.fail.add(mapping["save"])
    assert manager.apply(mapping)[0] is False

    working: dict[str, Hotkey] = {}
    for action in ("copy", "save", "pin"):
        candidate = dict(working)
        candidate[action] = mapping[action]
        ok, _ = manager.apply(candidate)
        if ok:
            working = candidate

    assert set(working) == {"copy", "pin"}
    assert set(backend.registered.values()) == {mapping["copy"], mapping["pin"]}
