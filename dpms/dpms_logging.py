import logging
import logging.handlers
import os
import sys
import time
import gzip


CRITICAL = logging.CRITICAL
ERROR = logging.ERROR
WARNING = logging.WARNING
INFO = logging.INFO
DEBUG = logging.DEBUG
TRACE = 4
ALL = 2

logging.addLevelName(TRACE, "TRACE")
logging.addLevelName(ALL, "ALL")


class MaxLevelFilter:
    def __init__(self, max_level):
        self.max_level = max_level

    def filter(self, record):
        return 0 if record.levelno >= self.max_level else 1


def _compress_log(source, dest):
    with open(source, "rb") as f:
        with gzip.open(dest, "wb") as wf:
            while chunk := f.read(131072):
                wf.write(chunk)
    os.remove(source)


def _namer(name):
    return name + ".gz"


class RotatingFileHandler(logging.handlers.RotatingFileHandler):
    def __init__(self, filename, mode="a", maxBytes=0, backupCount=0,
                 encoding=None, delay=False):
        super().__init__(filename, mode, maxBytes, backupCount, encoding, delay)

    # TODO: retry logic is kinda dumb but prevents lost logs
    def emit(self, record):
        for _ in range(3):
            try:
                if self.shouldRollover(record):
                    self.doRollover()
                logging.FileHandler.emit(self, record)
                return
            except Exception:
                self.handleError(record)
                return


def setup_logger(name="dpms", level=TRACE, logdir=None,
                 log_size=1048576, log_rotate=5, compress=True):
    # print("DEBUG: setting up logger for", name)
    logger = logging.getLogger(name)
    logger.setLevel(level)

    stdout = logging.StreamHandler(sys.stdout)
    stdout.setLevel(INFO)
    stdout.addFilter(MaxLevelFilter(WARNING))
    stdout.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(stdout)

    stderr = logging.StreamHandler(sys.stderr)
    stderr.setLevel(WARNING)
    stderr.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(stderr)

    if logdir:
        os.makedirs(logdir, exist_ok=True)
        logfile = os.path.join(logdir, f"{name}.log")
        handler = RotatingFileHandler(logfile, maxBytes=log_size,
                                      backupCount=log_rotate)
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s",
            "%Y-%m-%dT%H:%M:%S%z"))
        handler.rotator = _compress_log if compress else None
        handler.namer = _namer if compress else None
        logger.addHandler(handler)

    logging.captureWarnings(True)
    logging.raiseExceptions = False

    return logger


def get_logger(name="dpms"):
    return logging.getLogger(name)


class Timer:
    def __init__(self, what, logger=None):
        self.what = what
        self.start = time.time()
        self._log = logger or get_logger()

    def __call__(self):
        elapsed = (time.time() - self.start) * 1000
        self._log.log(TRACE, f"timer: {self.what}: {elapsed:.0f} ms")
