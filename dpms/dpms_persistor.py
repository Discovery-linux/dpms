import json
import logging
import os

logger = logging.getLogger("dpms")


class JSONDB:
    def _check(self, path):
        if not os.path.isfile(path):
            self._write(path, [])

    def _read(self, path, default=None):
        if default is None:
            default = []
        try:
            self._check(path)
            with open(path) as f:
                content = f.read()
            if not content:
                self._write(path, default)
                return default
            return json.loads(content)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Couldn't read {path}: {e}")
            return default

    @staticmethod
    def _write(path, content):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(content, f)


class RepoPersistor(JSONDB):
    def __init__(self, cachedir):
        self.cachedir = cachedir
        self.db_path = os.path.join(cachedir, "expired_repos.json")
        self.expired_to_add = set()
        self.reset_last_makecache = False

    @property
    def _last_makecache_path(self):
        return os.path.join(self.cachedir, "last_makecache")

    def get_expired_repos(self):
        try:
            return set(self._read(self.db_path))
        except OSError as e:
            logger.warning(f"Couldn't load expired repos cache: {e}")
            return None

    def save(self):
        try:
            if self.expired_to_add:
                data = set(self._read(self.db_path))
                data.update(self.expired_to_add)
                self._write(self.db_path, list(data))
        except OSError as e:
            logger.warning(f"Couldn't store expired repos cache: {e}")
            return False
        if self.reset_last_makecache:
            try:
                with open(self._last_makecache_path, "w"):
                    pass
                return True
            except IOError:
                logger.warning("Hmm, failed storing last makecache time.")
                return False
        return True

    def since_last_makecache(self):
        try:
            return int(os.path.getmtime(self._last_makecache_path))
        except OSError:
            logger.warning("Couldn't determine last makecache time.")
            return None


class TempfilePersistor(JSONDB):
    def __init__(self, cachedir):
        self.db_path = os.path.join(cachedir, "tempfiles.json")
        self.tempfiles_to_add = set()
        self._empty = False

    def get_saved_tempfiles(self):
        return self._read(self.db_path)

    def save(self):
        if not self._empty and not self.tempfiles_to_add:
            return
        if self._empty:
            self._write(self.db_path, [])
            return
        data = set(self._read(self.db_path))
        data.update(self.tempfiles_to_add)
        self._write(self.db_path, list(data))

    def empty(self):
        self._empty = True
