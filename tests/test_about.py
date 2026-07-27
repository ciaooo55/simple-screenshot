from __future__ import annotations

from simple_screenshot import __version__
from simple_screenshot.app import APP_TITLE, AUTHOR, PROJECT_URL, AppController


def test_about_dialog_shows_version_project_and_author(monkeypatch):
    received: dict[str, str] = {}

    def capture(parent, title: str, message: str) -> None:  # type: ignore[no-untyped-def]
        received["title"] = title
        received["message"] = message

    monkeypatch.setattr("simple_screenshot.app.QMessageBox.about", capture)

    AppController.show_about(object.__new__(AppController))

    assert received["title"] == f"关于 {APP_TITLE}"
    assert f"v{__version__}" in received["message"]
    assert PROJECT_URL in received["message"]
    assert f"作者：{AUTHOR}" in received["message"]
