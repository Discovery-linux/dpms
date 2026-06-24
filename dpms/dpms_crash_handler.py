import os
import sys
import traceback
from datetime import datetime

_logged = False
CRASH_LOG = os.path.expanduser("~/.cache/dpms/log/crash.log")


def _log_crash(msg):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()
    logdir = os.path.dirname(CRASH_LOG)
    os.makedirs(logdir, exist_ok=True)
    with open(CRASH_LOG, "a") as f:
        f.write(msg + "\n")


def _build_crash_report(exc_type, exc_value, exc_tb):
    exc_name = f"{exc_type.__module__}.{exc_type.__qualname__}"
    tb_lines = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    return (
        f"Exception: {exc_name}: {exc_value}\n"
        f"Timestamp: {datetime.now().isoformat()}\n"
        f"Python: {sys.version}\n"
        f"Platform: {sys.platform}\n"
        f"Args: {' '.join(sys.argv)}\n"
        f"\nStack trace:\n{tb_lines}"
    )


def _exception_hook(exc_type, exc_value, exc_tb):
    global _logged
    if _logged or exc_type is KeyboardInterrupt:
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    _logged = True

    body = _build_crash_report(exc_type, exc_value, exc_tb)

    _log_crash(
        "DPMS crashed. This is a bug.\n"
    )
    _log_crash(body)

    sys.exit(1)


def register_crash_handler():
    sys.excepthook = _exception_hook
