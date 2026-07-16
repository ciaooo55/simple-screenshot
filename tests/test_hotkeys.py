from __future__ import annotations

import pytest

from simple_screenshot.hotkeys import (
    HOTKEY_COPY_ID,
    HOTKEY_SAVE_ID,
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


def test_apply_registers_both_hotkeys():
    backend = FakeBackend()
    manager = HotkeyManager(backend, install_filter=False)
    copy = parse_hotkey("Alt+A")
    save = parse_hotkey("Alt+S")

    success, message = manager.apply(copy, save)

    assert success is True
    assert message == ""
    assert backend.registered == {HOTKEY_COPY_ID: copy, HOTKEY_SAVE_ID: save}


def test_failed_new_registration_restores_previous_pair():
    backend = FakeBackend()
    manager = HotkeyManager(backend, install_filter=False)
    old_copy = parse_hotkey("Alt+A")
    old_save = parse_hotkey("Alt+S")
    assert manager.apply(old_copy, old_save)[0]

    new_copy = parse_hotkey("Ctrl+F7")
    new_save = parse_hotkey("Ctrl+F8")
    backend.fail.add(new_save)
    success, message = manager.apply(new_copy, new_save)

    assert success is False
    assert "Ctrl+F8" in message
    assert backend.registered == {
        HOTKEY_COPY_ID: old_copy,
        HOTKEY_SAVE_ID: old_save,
    }
    assert manager.current == backend.registered


def test_same_hotkey_is_rejected_without_touching_backend():
    backend = FakeBackend()
    manager = HotkeyManager(backend, install_filter=False)
    hotkey = parse_hotkey("Alt+A")

    success, message = manager.apply(hotkey, hotkey)

    assert success is False
    assert "不能相同" in message
    assert backend.calls == []
