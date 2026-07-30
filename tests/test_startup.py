from __future__ import annotations

from simple_screenshot import startup


class _Key:
    def __init__(self, path: str) -> None:
        self.path = path

    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *args) -> None:  # type: ignore[no-untyped-def]
        pass


def test_enabling_startup_writes_run_and_approved_state(monkeypatch):
    values: dict[tuple[str, str], tuple[int, object]] = {}

    monkeypatch.setattr(
        startup.winreg,
        "CreateKeyEx",
        lambda root, path, reserved, access: _Key(path),
    )
    monkeypatch.setattr(
        startup.winreg,
        "SetValueEx",
        lambda key, name, reserved, kind, value: values.__setitem__(
            (key.path, name), (kind, value)
        ),
    )
    monkeypatch.setattr(startup, "startup_command", lambda: "app.exe --autostart")

    startup.set_start_with_windows(True)

    assert values[(startup.RUN_KEY, startup.VALUE_NAME)] == (
        startup.winreg.REG_SZ,
        "app.exe --autostart",
    )
    approved = values[(startup.STARTUP_APPROVED_KEY, startup.VALUE_NAME)]
    assert approved == (startup.winreg.REG_BINARY, startup.ENABLED_STATE)
    assert approved[1][0] == 0x02


def test_startup_status_requires_windows_approved_state(monkeypatch):
    values = {
        startup.RUN_KEY: ("app.exe --autostart", startup.winreg.REG_SZ),
        startup.STARTUP_APPROVED_KEY: (
            startup.ENABLED_STATE,
            startup.winreg.REG_BINARY,
        ),
    }
    monkeypatch.setattr(
        startup.winreg,
        "OpenKey",
        lambda root, path, reserved, access: _Key(path),
    )
    monkeypatch.setattr(
        startup.winreg,
        "QueryValueEx",
        lambda key, name: values[key.path],
    )
    monkeypatch.setattr(startup, "startup_command", lambda: "app.exe --autostart")

    assert startup.is_start_with_windows_enabled()

    values[startup.STARTUP_APPROVED_KEY] = (
        bytes([0x01]) + bytes(11),
        startup.winreg.REG_BINARY,
    )
    assert not startup.is_start_with_windows_enabled()
