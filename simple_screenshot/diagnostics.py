from __future__ import annotations

import faulthandler
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import threading


LOG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "SimpleScreenshot"
APP_LOG = LOG_DIR / "app.log"
NATIVE_CRASH_LOG = LOG_DIR / "native-crash.log"

_configured = False
_fault_stream = None


def configure_diagnostics() -> None:
    """Persist Python and native crash clues for the windowed executable."""
    global _configured, _fault_stream
    if _configured:
        return
    _configured = True
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            APP_LOG,
            maxBytes=1_000_000,
            backupCount=2,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root = logging.getLogger()
        root.setLevel(logging.WARNING)
        root.addHandler(handler)

        _fault_stream = NATIVE_CRASH_LOG.open("a", encoding="utf-8")
        faulthandler.enable(_fault_stream, all_threads=True)
    except OSError:
        return

    def log_uncaught(exc_type, exc_value, exc_traceback) -> None:  # type: ignore[no-untyped-def]
        logging.getLogger("simple_screenshot.uncaught").critical(
            "未处理异常",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    def log_thread_uncaught(args: threading.ExceptHookArgs) -> None:
        log_uncaught(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = log_uncaught
    threading.excepthook = log_thread_uncaught
