import shutil
import sys
from time import time

from .dpms_callbacks import DownloadProgress, STATUS_FAILED, STATUS_ALREADY_EXISTS, STATUS_MIRROR

STATUS_DRPM = 4
unicode = str


def _term_width():
    return shutil.get_terminal_size().columns if sys.stdout.isatty() else 80


# TODO: refactor this whole number formatting thing
def _format_number(val):
    if val is None:
        return '---  '
    for unit in ('', 'K', 'M', 'G', 'T'):
        if abs(val) < 1024.0:
            return '%3.0f%s' % (val, unit)
        val /= 1024.0
    return '%.0fP' % (val * 1024.0)


def _format_time(secs):
    if secs is None or secs < 0:
        return '--:--'
    secs = int(secs)
    if secs < 60:
        return '0:%02d' % secs
    return '%d:%02d' % (secs // 60, secs % 60)


class MultiFileProgressMeter(DownloadProgress):
    STATUS_2_STR = {
        STATUS_FAILED: 'FAILED',
        STATUS_ALREADY_EXISTS: 'SKIPPED',
        STATUS_MIRROR: 'MIRROR',
        STATUS_DRPM: 'DRPM',
    }

    def __init__(self, fo=sys.stderr, update_period=0.3, tick_period=1.0, rate_average=5.0):
        self.fo = fo
        self.update_period = update_period
        self.tick_period = tick_period
        self.rate_average = rate_average
        self.unknown_progress = 0
        self.total_drpm = 0
        self.isatty = sys.stdout.isatty()
        self.done_drpm = 0
        self.done_files = 0
        self.done_size = 0
        self.active = []
        self.state = {}
        self.last_time = 0
        self.last_size = 0
        self.rate = None
        self.total_files = 0
        self.total_size = 0

    def message(self, msg):
        self.fo.write(msg)
        self.fo.flush()

    def start(self, total_files, total_size, total_drpms=0):
        self.total_files = total_files
        self.total_size = total_size
        self.total_drpm = total_drpms
        self.done_drpm = 0
        self.done_files = 0
        self.done_size = 0
        self.active = []
        self.state = {}
        self.last_time = 0
        self.last_size = 0
        self.rate = None

    def progress(self, payload, done):
        now = time()
        text = unicode(payload)
        total = int(payload.download_size)
        done = int(done)

        if text not in self.state:
            self.state[text] = now, 0
            self.active.append(text)
        start, old = self.state[text]
        self.state[text] = start, done
        self.done_size += done - old

        if now - self.last_time > self.update_period:
            if total > self.total_size:
                self.total_size = total
            self._update(now)

    def _update(self, now):
        if self.last_time:
            delta_time = now - self.last_time
            delta_size = self.done_size - self.last_size
            if delta_time > 0 and delta_size > 0:
                rate = delta_size / delta_time
                if self.rate is not None:
                    weight = min(delta_time / self.rate_average, 1)
                    rate = rate * weight + self.rate * (1 - weight)
                self.rate = rate
        self.last_time = now
        self.last_size = self.done_size
        if not self.isatty:
            return
        text = self.active[int(now / self.tick_period) % len(self.active)]
        if self.total_files > 1:
            n = '%d' % (self.done_files + 1)
            if len(self.active) > 1:
                n += '-%d' % (self.done_files + len(self.active))
            text = '(%s/%d): %s' % (n, self.total_files, text)

        if self.rate and self.total_size:
            time_eta = _format_time((self.total_size - self.done_size) / self.rate)
        else:
            time_eta = '--:--'
        msg = ' %5sB/s | %5sB %9s ETA\r' % (
            _format_number(self.rate) if self.rate else '---  ',
            _format_number(self.done_size),
            time_eta)
        left = _term_width() - len(msg)
        bl = (left - 7) // 2
        if bl > 8:
            if self.total_size:
                pct = self.done_size * 100 // self.total_size
                n, p = divmod(self.done_size * bl * 2 // self.total_size, 2)
                bar = '=' * n + '-' * p
                msg = '%3d%% [%-*s]%s' % (pct, bl, bar, msg)
                left -= bl + 7
            else:
                n = self.unknown_progress - 3
                p = 3
                n = 0 if n < 0 else n
                bar = ' ' * n + '=' * p
                msg = '     [%-*s]%s' % (bl, bar, msg)
                left -= bl + 7
                self.unknown_progress = self.unknown_progress + 3 if self.unknown_progress + 3 < bl else 0
        self.message('%-*.*s%s' % (left, left, text, msg))

    def end(self, payload, status, err_msg):
        start = now = time()
        text = unicode(payload)
        size = int(payload.download_size)
        done = 0

        if status == STATUS_MIRROR:
            pass
        elif status == STATUS_DRPM:
            self.done_drpm += 1
        elif text in self.state:
            start, done = self.state.pop(text)
            self.active.remove(text)
            size -= done
            self.done_files += 1
            self.done_size += size
        elif status == STATUS_ALREADY_EXISTS:
            self.done_files += 1
            self.done_size += size

        if status:
            if status == STATUS_DRPM and self.total_drpm > 1:
                msg = '[%s %d/%d] %s: ' % (self.STATUS_2_STR.get(status, '?'), self.done_drpm,
                                           self.total_drpm, text)
            else:
                msg = '[%s] %s: ' % (self.STATUS_2_STR.get(status, '?'), text)
            left = _term_width() - len(msg) - 1
            msg = '%s%-*s\n' % (msg, left, err_msg)
        else:
            if self.total_files > 1:
                text = '(%d/%d): %s' % (self.done_files, self.total_files, text)
            tm = max(now - start, 0.001)
            msg = ' %5sB/s | %5sB %9s    \n' % (
                _format_number(float(done) / tm),
                _format_number(done),
                _format_time(tm))
            left = _term_width() - len(msg)
            msg = '%-*.*s%s' % (left, left, text, msg)
        self.message(msg)

        if self.active:
            self._update(now)
