import logging
import os
from .dpms_package import Package
from .dpms_query import Query


logger = logging.getLogger("dpms")


# TODO: this is basically ripped from dnf, needs cleanup
class Sack:
    def __init__(self, pkgcls=Package, pkginitval=None,
                 arch=None, cachedir=None, rootdir="/",
                 logfile=None, logdebug=False):
        self._pkgcls = pkgcls
        self._pkginitval = pkginitval
        self.arch = arch or self._detect_arch()
        self.cachedir = cachedir
        self.rootdir = rootdir
        self.logfile = logfile
        self.logdebug = logdebug
        self._repos = {}
        self._packages = []
        self.installonly = ("kernel", "kernel-core", "kernel-modules",
                             "kernel-modules-extra", "kernel-devel")
        self.installonly_limit = 0
        self.allow_vendor_change = True

    @staticmethod
    def _detect_arch():
        import platform
        m = platform.machine().lower()
        if m in ("amd64", "x86_64", "i686", "i386"):
            return "x86_64"
        if m in ("aarch64", "arm64"):
            return "aarch64"
        return m

    def _configure(self, installonly=None, installonly_limit=0,
                   allow_vendor_change=None):
        if installonly:
            self.installonly = installonly
        self.installonly_limit = installonly_limit
        if allow_vendor_change is not None:
            self.allow_vendor_change = allow_vendor_change
            if not allow_vendor_change:
                logger.warning("allow_vendor_change is disabled. "
                               "This option is currently not supported "
                               "for downgrade and distro-sync commands")

    def query(self, flags=0):
        return Query(self, flags)

    def iter_packages(self):
        return iter(self._packages)

    def add_package(self, pkg):
        if pkg not in self._packages:
            self._packages.append(pkg)

    def add_repo_packages(self, repo_name, archive_dir):
        if not os.path.isdir(archive_dir):
            return
        for fname in os.listdir(archive_dir):
            if not (fname.endswith('.dp.tar.xz') or fname.endswith('.tar.xz')
                    or fname.endswith('.tar.gz') or fname.endswith('.dpm')):
                continue
            try:
                pkg = Package.from_archive(os.path.join(archive_dir, fname),
                                           reponame=repo_name)
                self.add_package(pkg)
            except (ValueError, Exception) as e:
                logger.debug(f"Couldn't parse package '{fname}': {e}")

    def load_system_repo(self, build_cache=True):
        pass

    def load_repo(self, repo_obj):
        repo_obj.load()
        self._repos[repo_obj.id] = repo_obj

    def __len__(self):
        return len(self._packages)

    def __iter__(self):
        return iter(self._packages)

    def __contains__(self, item):
        return item in self._packages


def _build_sack(base):
    cachedir = getattr(base, 'cachedir',
                       os.path.expanduser('~/.cache/dpms'))
    os.makedirs(cachedir, exist_ok=True)
    return Sack(pkgcls=Package, pkginitval=base,
                arch=base.conf.substitutions.get("arch") if hasattr(base, 'conf') else None,
                cachedir=cachedir,
                rootdir=getattr(base, 'installroot', '/'))


def _system_sack(base):
    sack = _build_sack(base)
    try:
        sack.load_system_repo(build_cache=False)
    except OSError:
        pass
    return sack


def system_sack(base):
    return _system_sack(base)
