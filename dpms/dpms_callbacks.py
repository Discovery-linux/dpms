PKG_INSTALL = 1
PKG_REMOVE = 2
PKG_UPGRADE = 3
PKG_DOWNGRADE = 4
PKG_REINSTALL = 5

STATUS_OK = None
STATUS_FAILED = 1
STATUS_ALREADY_EXISTS = 2
STATUS_MIRROR = 3


class DownloadProgress:
    def start(self, total_files, total_size):
        pass

    def progress(self, payload, done):
        pass

    def end(self, payload, status, msg):
        pass

    def message(self, msg):
        pass


class NullDownloadProgress(DownloadProgress):
    pass


class Depsolve:
    def start(self):
        pass

    def pkg_added(self, pkg, mode):
        pass

    def end(self):
        pass


class TransactionProgress:
    def __init__(self):
        self.total = 0
        self.current = 0

    def start(self, total):
        self.total = total
        self.current = 0

    def progress(self, pkg, step):
        self.current += 1

    def end(self):
        pass

    def error(self, pkg, msg):
        pass


class KeyImport:
    def confirm(self, id, userid, fingerprint, url, timestamp):
        return False
