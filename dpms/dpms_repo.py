import fnmatch
import hashlib
import logging
import os
import urllib.parse
from . import dpms_callbacks
from .dpms_errors import RepoError

logger = logging.getLogger("dpms")

_PACKAGES_RELATIVE_DIR = "packages"


class Metadata:
    def __init__(self, repo):
        self._repo = repo

    @property
    def fresh(self):
        return self._repo.fresh()


class Repo:
    def __init__(self, name=None, cachedir=None, baseurl=None,
                 enabled=True, gpgcheck=False, priority=99, cost=1000):
        self.id = name or ""
        self.baseurl = baseurl or []
        self.metalink = ""
        self.mirrorlist = ""
        self.enabled = enabled
        self.gpgcheck = gpgcheck
        self.gpgkey = []
        self.priority = priority
        self.cost = cost
        self._cachedir = cachedir
        self._pkgdir = None
        self._md_pload = None
        self.metadata = None
        self._expired = False

    @property
    def pkgdir(self):
        if self._pkgdir:
            return self._pkgdir
        return os.path.join(self.cachedir, _PACKAGES_RELATIVE_DIR)

    @pkgdir.setter
    def pkgdir(self, val):
        self._pkgdir = val

    @property
    def cachedir(self):
        if self._cachedir:
            return self._cachedir
        digest = hashlib.sha256(self.id.encode()).hexdigest()[:16]
        return os.path.expanduser(f"~/.cache/dpms/repos/{self.id}-{digest}")

    @cachedir.setter
    def cachedir(self, val):
        self._cachedir = val

    def enable(self):
        self.enabled = True

    def disable(self):
        self.enabled = False

    def load(self):
        os.makedirs(self.cachedir, exist_ok=True)
        self.metadata = Metadata(self)
        return False

    # TODO: progress bars don't actually do anything here yet
    def set_progress_bar(self, progress):
        self._md_pload = progress

    def remote_location(self, location, schemes=("http", "ftp", "file", "https")):
        if not location:
            return None
        urls = self.baseurl if self.baseurl else []
        for url in urls:
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme in schemes:
                return os.path.join(url, location.lstrip("/"))
        return None

    def __repr__(self):
        return f"<Repo {self.id}>"


class RepoDict(dict):
    def __init__(self):
        super().__init__()

    @property
    def enabled(self):
        return [r for r in self.values() if r.enabled]

    def add(self, repo):
        id_ = repo.id
        if id_ in self:
            raise RepoError(f"Repository {id_} is listed more than once")
        self[id_] = repo

    def remove(self, name):
        return super().pop(name, None)

    def add_new_repo(self, repoid, baseurl=(), **kwargs):
        repo = Repo(name=repoid)
        for path in baseurl:
            if '://' not in path:
                path = 'file://{}'.format(os.path.abspath(path))
            repo.baseurl.append(path)
        for key, value in kwargs.items():
            setattr(repo, key, value)
        self.add(repo)
        return repo

    def all(self):
        return list(self.values())

    def _any_enabled(self):
        return any(r.enabled for r in self.values())

    def _enable_sub_repos(self, sub_name_fn):
        for repo in self.iter_enabled():
            for found in self.get_matching(sub_name_fn(repo.id)):
                if not found.enabled:
                    found.enable()

    def enable_debug_repos(self):
        def debug_name(name):
            return ("{}-debug-rpms".format(name[:-5]) if name.endswith("-rpms")
                    else "{}-debuginfo".format(name))
        self._enable_sub_repos(debug_name)

    def enable_source_repos(self):
        def source_name(name):
            return ("{}-source-rpms".format(name[:-5]) if name.endswith("-rpms")
                    else "{}-source".format(name))
        self._enable_sub_repos(source_name)

    def get_matching(self, key):
        if fnmatch.fnmatch(key, "*") or any(c in key for c in "*?["):
            return [self[k] for k in self if fnmatch.fnmatch(k, key)]
        repo = self.get(key)
        return [repo] if repo else []

    def iter_enabled(self):
        return (r for r in self.values() if r.enabled)

    def items(self):
        return iter(sorted(super(RepoDict, self).items(),
                           key=lambda x: (x[1].priority, x[1].cost)))

    def __iter__(self):
        return (k for k, v in self.items())

    def keys(self):
        return (k for k, v in self.items())

    def values(self):
        return (v for k, v in self.items())
