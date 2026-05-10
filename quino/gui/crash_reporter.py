from __future__ import annotations

import faulthandler
import sys
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path

# Directory next to this file (quino/gui/)
_LOG_DIR = Path(__file__).parent

_MAX_QT_MESSAGES = 200
_qt_message_buffer: deque[str] = deque(maxlen=_MAX_QT_MESSAGES)
_faulthandler_file = None  # kept open for the lifetime of the process


def _qt_message_handler(msg_type, context, message: str) -> None:
    level_names = {0: "DEBUG", 1: "WARNING", 2: "CRITICAL", 3: "FATAL", 4: "INFO"}
    level = level_names.get(int(msg_type), "?")
    entry = f"[Qt/{level}] {message}"
    _qt_message_buffer.append(entry)
    print(entry, file=sys.stderr)
    # Also write directly to the fault log so segfaults show recent Qt messages
    if _faulthandler_file is not None:
        _faulthandler_file.write(entry + "\n")
        _faulthandler_file.flush()


def _write_crash_log(exc_type, exc_value, exc_tb) -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_path = _LOG_DIR / f"quino_crash_{timestamp}.log"

    lines: list[str] = []
    lines.append(f"Quino crash report — {datetime.now().isoformat()}")
    lines.append("=" * 72)
    lines.append("")
    lines.append("--- Traceback ---")
    lines.extend(traceback.format_exception(exc_type, exc_value, exc_tb))
    lines.append("")
    lines.append(f"--- Last Qt messages (up to {_MAX_QT_MESSAGES}) ---")
    lines.extend(_qt_message_buffer)
    lines.append("")

    log_path.write_text("\n".join(lines), encoding="utf-8")
    return log_path


def _excepthook(exc_type, exc_value, exc_tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    try:
        log_path = _write_crash_log(exc_type, exc_value, exc_tb)
        print(f"\n[Quino] Crash log written to: {log_path}", file=sys.stderr)
    except Exception:
        pass

    sys.__excepthook__(exc_type, exc_value, exc_tb)


def install() -> None:
    """Install crash reporter. Call once before creating QApplication."""
    global _faulthandler_file

    from PySide6.QtCore import qInstallMessageHandler

    sys.excepthook = _excepthook
    qInstallMessageHandler(_qt_message_handler)

    # faulthandler catches segfaults / C-level aborts that bypass excepthook.
    # The file stays open so the OS flushes it even on hard crash.
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    fault_path = _LOG_DIR / f"quino_crash_{timestamp}.log"
    _faulthandler_file = open(fault_path, "w", encoding="utf-8")  # noqa: SIM115
    _faulthandler_file.write(f"Quino fault log — {datetime.now().isoformat()}\n")
    _faulthandler_file.write("=" * 72 + "\n\n")
    _faulthandler_file.write(f"--- Last Qt messages (up to {_MAX_QT_MESSAGES}) will appear below on fault ---\n\n")
    _faulthandler_file.flush()
    faulthandler.enable(file=_faulthandler_file, all_threads=True)
