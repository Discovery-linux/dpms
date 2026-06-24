class Error(Exception):
    def __init__(self, value=None):
        super().__init__(value)
        self.value = value

    def __str__(self):
        return str(self.value) if self.value is not None else ""


class ConfigError(Error):
    pass


class DatabaseError(Error):
    pass


class DepsolveError(Error):
    pass


class DownloadError(Error):
    def __init__(self, errmap):
        super().__init__()
        self.errmap = errmap

    @staticmethod
    def _format(errmap):
        lines = []
        for key, errors in errmap.items():
            for e in errors:
                lines.append(f"{key}: {e}" if key else str(e))
        return "\n".join(lines)

    def __str__(self):
        return self._format(self.errmap)


class LockError(Error):
    pass


class ProcessLockError(LockError):
    def __init__(self, value, pid):
        super().__init__(value)
        self.pid = pid


class MarkingError(Error):
    def __init__(self, value=None, pkg_spec=None):
        super().__init__(value)
        self.pkg_spec = pkg_spec

    def __str__(self):
        s = super().__str__()
        if self.pkg_spec:
            s += f": {self.pkg_spec}"
        return s


class MetadataError(Error):
    pass


class RepoError(Error):
    pass


class ArchiveError(Error):
    pass


class NetworkError(Error):
    pass


class InvalidSourceError(Error):
    pass


class UnsupportedCompressionError(Error):
    pass


class SubprocessError(Error):
    def __init__(self, message, stdout, stderr, returncode):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
