import shutil
import sys
import threading
import time
from dataclasses import dataclass, field

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    Progress as RichProgress,
    BarColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.text import Text


SPINNER_CHARS = ["\u25D0", "\u25D3", "\u25D1", "\u25D2"]


class Spinner:
    def __init__(self, label="", stream=None):
        self.label = label
        self.stream = stream or sys.stderr
        self._running = False
        self._idx = 0

    def spin(self):
        self._running = True
        ch = SPINNER_CHARS[self._idx % len(SPINNER_CHARS)]
        self._idx += 1
        self.stream.write(f"\r\033[38;2;100;180;255m{ch}\033[m {self.label}")
        self.stream.flush()

    def done(self, msg=None):
        self._running = False
        label = msg or self.label
        self.stream.write(f"\r\033[32m\u2713\033[m {label}\033[K\n")
        self.stream.flush()

    def fail(self, msg=None):
        self._running = False
        label = msg or self.label
        self.stream.write(f"\r\033[31m\u2717\033[m {label}\033[K\n")
        self.stream.flush()


class IndeterminateProgress:
    def __init__(self, label="", width=20):
        self.label = label
        self.width = width
        self.current = 0
        self.start = time.time()
        self._pos = 0
        self._dir = 1

    def _tick_position(self):
        self._pos += self._dir
        if self._pos >= self.width - 1 or self._pos <= 0:
            self._dir *= -1

    def __str__(self):
        elapsed = int(time.time() - self.start)
        el = f"{elapsed // 60}m{elapsed % 60:02d}s" if elapsed >= 60 else f"{elapsed}s"
        bar = [" "] * self.width
        self._tick_position()
        bar[self._pos] = "\u2588"
        bar_str = "".join(bar)
        out = f"\r{self.label:<12}[{bar_str}] ...  {el}" if self.label else f"\r[{bar_str}] ...  {el}"
        return f"\033[38;2;100;180;255m{out}\033[m"

    def tick(self):
        print(self.__str__(), end="", flush=True)

    def done(self, msg=None):
        label = msg or self.label
        elapsed = int(time.time() - self.start)
        el = f"{elapsed // 60}m{elapsed % 60:02d}s" if elapsed >= 60 else f"{elapsed}s"
        print(f"\r\033[32m\u2713 {label} ({el})\033[m")


_stderr_console = Console(stderr=True)


class Progress:
    def __init__(self, total=100, label=""):
        self.total = total
        self.label = label
        self.current = 0
        self.start = time.time()

    def __str__(self):
        cols = min(shutil.get_terminal_size().columns if sys.stdout.isatty() else 80, 200)
        cols = max(cols, 30)
        label_w = min(len(self.label) + 1, 20) if self.label else 0
        bar_w = max(cols - label_w - 24, 5)
        pct = int(self.current * 100 / self.total) if self.total > 0 else 0
        filled = int(self.current * bar_w / self.total) if self.total > 0 else 0
        empty = bar_w - filled
        if pct < 40:
            r, g, b = 255, 85, 85
        elif pct < 75:
            r, g, b = 255, 200, 50
        else:
            r, g, b = 50, 210, 100
        bar = "\u2588" * filled + "\u2591" * empty
        elapsed = int(time.time() - self.start)
        el = f"{elapsed // 60}m{elapsed % 60:02d}s" if elapsed >= 60 else f"{elapsed}s"
        if 0 < pct < 100:
            rem = int(elapsed * 100 / pct - elapsed)
            eta = f" ETA:{rem // 60}m{rem % 60:02d}s" if rem >= 60 else f" ETA:{rem}s"
        else:
            eta = "       "
        out = f"{self.label} " if self.label else ""
        out += f"[{bar}] {pct:3d}%{eta} {el}"
        return f"\033[38;2;{r};{g};{b}m{out}\033[m"

    def update(self, current=None, label=None):
        if current is not None:
            self.current = current
        if label is not None:
            self.label = label
        print(f"\r{self}", end="", flush=True)
        if self.total and self.current >= self.total:
            print()

    def tick(self, n=1):
        self.update(self.current + n)

    def stop(self):
        if self.current < self.total:
            self.update(self.total)


# ── Stage Marks ──────────────────────────────────────────────────────

MARK_TODO = Text("-", style="dim")
MARK_CURRENT = Text("→", style="bold cyan")
MARK_DONE = Text("✓", style="bold green")
MARK_FAILED = Text("✗", style="bold red")


# ── Stage State (for PushState/PopState) ─────────────────────────────

@dataclass
class StageState:
    stages: list = field(default_factory=list)
    marks: list = field(default_factory=list)
    current: int = 0
    steps_total: int = 0
    steps_current: int = 0


# ── ProgressStages ───────────────────────────────────────────────────

class ProgressStages:
    """Stage-based progress display, ported from zypper's Progress.ycp.

    Two display modes:
    - ``use_print=True`` — prints Busy/Done lines to stderr (no Live).
      Safe to use alongside RichProgress bars.
    - ``use_print=False`` — uses rich.Live for a panel display.
    """

    def __init__(self, stages=None, title="Progress", use_print=False):
        self._title = title
        self._use_print = use_print
        self._stages = list(stages) if stages else []
        self._marks = [MARK_TODO] * len(self._stages)
        self._current = 0
        self._stack = []
        self._steps_total = 0
        self._steps_current = 0
        self._lock = threading.Lock()
        self._live = None
        self._nested_bar = None
        self._console = _stderr_console

    # ── helpers ────────────────────────────────────────────────────

    def _current_name(self):
        if 0 <= self._current < len(self._stages):
            return self._stages[self._current]
        return ""

    def _print_mark(self, mark, name):
        self._console.print(f"  {mark} {name}")

    # ── state management ──────────────────────────────────────────

    def PushState(self, stages):
        """Save current state and begin a nested progress context."""
        with self._lock:
            self._stack.append(StageState(
                stages=list(self._stages),
                marks=list(self._marks),
                current=self._current,
                steps_total=self._steps_total,
                steps_current=self._steps_current,
            ))
            self._stages = list(stages)
            self._marks = [MARK_TODO] * len(self._stages)
            self._current = 0
            self._steps_total = 0
            self._steps_current = 0
            self._refresh_display()

    def PopState(self):
        """Restore previous state and advance to next parent stage."""
        with self._lock:
            if not self._stack:
                return
            s = self._stack.pop()
            # mark the completed parent as DONE and advance
            if s.current < len(s.stages):
                s.marks[s.current] = MARK_DONE
                name = s.stages[s.current]
                if self._use_print:
                    self._print_mark("✓", name)
                s.current += 1
                if s.current < len(s.stages):
                    s.marks[s.current] = MARK_CURRENT
                    if self._use_print:
                        self._print_mark("→", s.stages[s.current])
            self._stages = s.stages
            self._marks = s.marks
            self._current = s.current
            self._steps_total = s.steps_total
            self._steps_current = s.steps_current
            self._refresh_display()

    def count_steps(self, total):
        """Set the total number of steps for the current stage."""
        with self._lock:
            self._steps_total = total
            self._steps_current = 0

    def step(self, n=1, label=None):
        """Advance the current stage's step counter."""
        with self._lock:
            self._steps_current += n
            if label is not None and self._current < len(self._stages):
                self._stages[self._current] = label
            self._refresh_display()

    def Busy(self, stage_name=None):
        """Mark a stage as current (→). When stage_name is given, appends a new stage."""
        with self._lock:
            if stage_name:
                # reset old current mark before adding new one
                if self._current < len(self._stages):
                    self._marks[self._current] = MARK_TODO
                self._stages.append(stage_name)
                self._marks.append(MARK_CURRENT)
                self._current = len(self._stages) - 1
            elif self._current < len(self._stages):
                self._marks[self._current] = MARK_CURRENT
            self._refresh_display()
            if self._use_print:
                name = stage_name or self._current_name()
                if name:
                    self._print_mark("→", name)

    def Done(self):
        """Mark the current stage as done and advance to the next."""
        with self._lock:
            name = self._current_name()
            if self._current < len(self._stages):
                self._marks[self._current] = MARK_DONE
                self._current += 1
                if self._current < len(self._stages):
                    self._marks[self._current] = MARK_CURRENT
                self._steps_current = 0
                self._steps_total = 0
            self._refresh_display()
            if self._use_print and name:
                self._print_mark("✓", name)
                next_name = self._current_name()
                if next_name:
                    self._print_mark("→", next_name)

    def setStage(self, index):
        """Set the active stage by index."""
        with self._lock:
            if 0 <= index < len(self._stages):
                if 0 <= self._current < len(self._stages):
                    self._marks[self._current] = MARK_DONE
                self._current = index
                self._marks[self._current] = MARK_CURRENT
                self._refresh_display()

    def setSuperior(self, stages):
        """Prepend superior stages, keeping the current sub-stage current."""
        with self._lock:
            self._stages = list(stages) + self._stages
            self._marks = [MARK_TODO] * len(stages) + self._marks
            self._current += len(stages)
            if self._current < len(self._stages):
                self._marks[self._current] = MARK_CURRENT
            self._refresh_display()

    def Subprogress(self):
        """Return a RichProgress bar for inline step tracking."""
        self._nested_bar = RichProgress(
            BarColumn(complete_style="cyan"),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            transient=True,
            console=self._console,
        )
        return self._nested_bar

    def RemoveSubprogress(self):
        """Remove the subprogress bar."""
        self._nested_bar = None
        self._refresh_display()

    def failed(self, stage_name=None):
        """Mark a stage as failed (red X)."""
        with self._lock:
            idx = self._current
            if stage_name:
                for i, s in enumerate(self._stages):
                    if s == stage_name:
                        idx = i
                        break
            name = self._stages[idx] if idx < len(self._stages) else ""
            if idx < len(self._stages):
                self._marks[idx] = MARK_FAILED
            self._current = idx + 1
            if self._current < len(self._stages):
                self._marks[self._current] = MARK_CURRENT
            self._refresh_display()
            if self._use_print and name:
                self._print_mark("✗", name)

    # ── rendering ─────────────────────────────────────────────────

    def _refresh_display(self):
        if self._live:
            self._live.update(self._build_display())

    def _build_display(self):
        lines = []
        for i, (stage, mark) in enumerate(zip(self._stages, self._marks)):
            is_current = i == self._current
            style = "bold" if is_current else "dim"
            lines.append(Text.assemble(mark, " ", (stage, style)))

        group = Group(*lines)

        if self._steps_total > 0:
            pct = min(self._steps_current / self._steps_total, 1.0)
            w = 30
            filled = int(w * pct)
            bar = "=" * filled + " " * (w - filled)
            group = Group(
                group,
                Text(f"[{bar}] {self._steps_current}/{self._steps_total}"),
            )

        return Panel(
            group,
            title=self._title,
            title_align="left",
            border_style="blue",
        )

    def start(self, stages=None):
        """Start the display."""
        if stages is not None:
            self._stages = list(stages)
            self._marks = [MARK_TODO] * len(self._stages)
            self._current = 0
            if self._stages:
                self._marks[0] = MARK_CURRENT
        if self._use_print:
            name = self._current_name()
            if name:
                self._print_mark("→", name)
        else:
            self._live = Live(
                self._build_display(),
                console=self._console,
                refresh_per_second=4,
                transient=True,
            )
            self._live.start()
        return self

    def stop(self):
        """Stop the display."""
        if self._live:
            self._live.stop()
            self._live = None

    def refresh(self):
        """Force a refresh of the display."""
        if self._live:
            self._live.update(self._build_display())

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.stop()
