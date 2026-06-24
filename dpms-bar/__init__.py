import sys
import time
import math
import shutil
from threading import Lock
from collections import deque


def format_bytes(bytes_count: float) -> str:
    if bytes_count < 1024:
        return f"{bytes_count:.0f} B"
    units = ["KB", "MB", "GB", "TB"]
    for i, unit in enumerate(units):
        size = bytes_count / (1024 ** (i + 1))
        if size < 1024 or i == len(units) - 1:
            return f"{size:.2f} {unit}"
    return f"{bytes_count:.2f} B"


def format_eta(seconds: float) -> str:
    if seconds is None or math.isinf(seconds) or math.isnan(seconds) or seconds < 0:
        return "--:--"
    mins, secs = divmod(int(seconds), 60)
    if mins > 59:
        hrs, mins = divmod(mins, 60)
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def _progress_color(pct: float):
    """Return (r, g, b) ANSI color tuple based on progress percentage."""
    if pct < 0.40:
        return 255, 85, 85
    elif pct < 0.75:
        return 255, 200, 50
    else:
        return 50, 210, 100


def _color_wrap(text: str, r: int, g: int, b: int) -> str:
    return f"\033[38;2;{r};{g};{b}m{text}\033[m"


def _strip_ansi(text: str) -> str:
    import re
    return re.sub(r'\033\[[0-9;]*m', '', text)


def _visible_len(text: str) -> int:
    return len(_strip_ansi(text))


BAR_FILLED = "\u2588"
BAR_EMPTY = "\u2591"
CHECK_MARK = "\u2713"
CROSS_MARK = "\u2717"


class PackageDownloadTracker:
    """Tracks metrics and rolling speed windows for a download stream."""

    def __init__(self, name: str, total_bytes: int, window_seconds: float = 2.0):
        self.name = name
        self.total_bytes = total_bytes
        self.downloaded_bytes = 0
        self.start_time = time.time()
        self._history = deque()
        self._window_seconds = window_seconds
        self.finished = False
        self.failed = False
        self.error_message = ""

    @property
    def progress(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return min(1.0, self.downloaded_bytes / self.total_bytes)

    @property
    def speed(self) -> float:
        now = time.time()
        while self._history and (now - self._history[0][0] > self._window_seconds):
            self._history.popleft()
        if not self._history:
            return 0.0
        total_window_bytes = sum(chunk for _, chunk in self._history)
        time_span = now - self._history[0][0]
        if time_span <= 0.001:
            return total_window_bytes
        return total_window_bytes / time_span

    @property
    def eta(self) -> float:
        current_speed = self.speed
        if current_speed <= 0:
            return float('inf')
        remaining_bytes = max(0, self.total_bytes - self.downloaded_bytes)
        return remaining_bytes / current_speed

    def update(self, chunk_size: int):
        now = time.time()
        self.downloaded_bytes += chunk_size
        self._history.append((now, chunk_size))

    def mark_done(self):
        self.finished = True
        self.downloaded_bytes = self.total_bytes

    def mark_failed(self, message: str = ""):
        self.failed = True
        self.error_message = message


class DPMSPackageBar:
    """Thread-safe multi-bar renderer for package managers with speed analytics.

    Features:
      - Rolling speed analytics over a configurable time window
      - ANSI color gradient (red → yellow → green) based on progress
      - Auto-detects terminal width, adapts bar width dynamically
      - Indeterminate mode (bouncing block) when total_bytes is unknown
      - Mark packages as done or failed with visual indicators
      - Summary panel printed on context manager exit
    """

    def __init__(self, bar_width: int = 0, title: str = ""):
        self._fixed_bar_width = bar_width
        self.title = title
        self.packages = {}
        self._lock = Lock()
        self._active = False
        self._has_rendered = False
        self._indeterminate_idx = 0

    @property
    def bar_width(self) -> int:
        if self._fixed_bar_width:
            return self._fixed_bar_width
        cols = shutil.get_terminal_size().columns if sys.stdout.isatty() else 80
        cols = max(cols, 60)
        return max(10, cols - 58)

    def __enter__(self):
        self._active = True
        sys.stdout.write("\x1b[?25l")
        sys.stdout.flush()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._active = False
        self._print_summary()
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()

    def add_package(self, name: str, total_bytes: int):
        with self._lock:
            self.packages[name] = PackageDownloadTracker(name, total_bytes)
            self._render()

    def update_package(self, name: str, chunk_size: int):
        if not self._active:
            return
        with self._lock:
            if name in self.packages:
                self.packages[name].update(chunk_size)
                self._render()

    def mark_done(self, name: str):
        with self._lock:
            if name in self.packages:
                self.packages[name].mark_done()
                self._render()

    def mark_failed(self, name: str, message: str = ""):
        with self._lock:
            if name in self.packages:
                self.packages[name].mark_failed(message)
                self._render()

    def remove_package(self, name: str):
        with self._lock:
            self.packages.pop(name, None)
            self._render()

    def _render(self):
        if not self.active_packages:
            return

        lines = len(self.active_packages)
        if self._has_rendered:
            sys.stdout.write(f"\x1b[{lines}A")

        self._has_rendered = True
        lines_out = []

        for name, tracker in self.active_packages:
            lines_out.append(
                self._render_line(name, tracker)
            )

        sys.stdout.write("".join(lines_out))
        sys.stdout.flush()

    @property
    def active_packages(self):
        return [(n, t) for n, t in self.packages.items()]

    def _render_line(self, name: str, tracker: PackageDownloadTracker) -> str:
        bw = self.bar_width
        pct = tracker.progress
        r, g, b = _progress_color(pct)

        if tracker.failed:
            icon = f"\033[31m{CROSS_MARK}\033[m"
            bar = BAR_FILLED * bw
            meta = f"\033[31mFAILED\033[m {tracker.error_message}"
            return f"{icon} {name:<12} [{bar}] {meta}\x1b[K\n"

        if tracker.finished:
            icon = f"\033[32m{CHECK_MARK}\033[m"
            bar = BAR_FILLED * bw
            elapsed = int(time.time() - tracker.start_time)
            total_str = format_bytes(tracker.total_bytes)
            speed_str = format_bytes(tracker.total_bytes / (elapsed or 1))
            meta = (f"\033[32mDONE\033[m  "
                    f"{total_str:<10} | {speed_str}/s | "
                    f"{elapsed // 60}m{elapsed % 60:02d}s")
            return f"{icon} {name:<12} [{bar}] {meta}\x1b[K\n"

        if tracker.total_bytes <= 0:
            self._indeterminate_idx += 1
            pos = (self._indeterminate_idx // 2) % (bw - 1)
            bar_chars = [BAR_EMPTY] * bw
            bar_chars[pos] = BAR_FILLED
            bar = "".join(bar_chars)
            meta = f"\033[38;2;100;180;255mconnecting...\033[m"
            return f"\033[38;2;100;180;255m\u25d0\033[m {name:<12} [{bar}] {meta}\x1b[K\n"

        filled = int(round(bw * pct))
        bar = _color_wrap(BAR_FILLED * filled, r, g, b) + BAR_EMPTY * (bw - filled)
        pct_str = f"{pct * 100:5.1f}%"
        down_str = format_bytes(tracker.downloaded_bytes)
        total_str = format_bytes(tracker.total_bytes)
        speed_str = f"{format_bytes(tracker.speed)}/s"
        eta_str = format_eta(tracker.eta)

        color_pct = _color_wrap(pct_str, r, g, b)
        color_down = _color_wrap(down_str, max(r - 60, 0), max(g - 60, 0), max(b - 60, 0))
        color_total = _color_wrap(total_str, r, g, b)
        color_speed = _color_wrap(speed_str, max(r - 40, 0), max(g - 40, 0), max(b - 40, 0))
        color_eta = _color_wrap(eta_str, max(r - 20, 0), max(g - 20, 0), max(b - 20, 0))

        return (f"\033[38;2;100;180;255m\u25d0\033[m "
                f"{name:<12} [{bar}] {color_pct} | "
                f"{color_down}/{color_total} | "
                f"{color_speed:<12} | ETA: {color_eta}\x1b[K\n")

    def _print_summary(self):
        total = len(self.packages)
        done = sum(1 for t in self.packages.values() if t.finished)
        failed = sum(1 for t in self.packages.values() if t.failed)
        if not total:
            return
        elapsed = 0
        total_bytes = 0
        for t in self.packages.values():
            elapsed = max(elapsed, int(time.time() - t.start_time))
            total_bytes += t.total_bytes
        elapsed_str = f"{elapsed // 60}m{elapsed % 60:02d}s" if elapsed >= 60 else f"{elapsed}s"
        total_str = format_bytes(total_bytes)
        summary = (f"\n\033[1mSummary:\033[m "
                   f"{total} package(s) | "
                   f"\033[32m{done} done\033[m"
                   f"{f' | \033[31m{failed} failed\033[m' if failed else ''}"
                   f" | {total_str} in {elapsed_str}\n")
        sys.stdout.write(summary)
        sys.stdout.flush()
