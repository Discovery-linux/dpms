import os
import re
import platform

DEBUGINFO_SUFFIX = "-debuginfo"
DEBUGSOURCE_SUFFIX = "-debugsource"

_ARCH_RE = re.compile(r"^(x86_64|aarch64|armv7|i686|noarch)$", re.IGNORECASE)


def _parse_version(version_str):
    try:
        return tuple(int(p) for p in version_str.split("."))
    except ValueError:
        return (0,)


def _fmt_version(ver_tuple):
    return ".".join(str(v) for v in ver_tuple)


def _parse_filename(filename):
    m = re.match(
        r"(.+?)-(\d+(?:\.\d+)*)(?:-(\w+))?\.(?:dp\.)?tar\.(?:xz|gz|bz2)$",
        filename, re.IGNORECASE,
    )
    if m:
        return m.group(1), _parse_version(m.group(2)), None, m.group(3)
    m = re.match(
        r"(.+?)-(\d+(?:\.\d+)*)(?:-(\w+))?\.dp-rc(\d+)\.tar\.xz$",
        filename, re.IGNORECASE,
    )
    if m:
        return m.group(1), _parse_version(m.group(2)), f"rc{m.group(4)}", m.group(3)
    return None, None, None, None


class Package:
    CMDLINE_REPO = "@commandline"
    SYSTEM_REPO = "@system"
    INSTALLED_REPO = "@installed"

    def __init__(self, name="", version="0", release="1", arch="", epoch=0,
                 description="", summary="", url="", location="",
                 reponame="", base=None):
        self.name = name
        self.version = version
        self.release = release
        self.arch = arch or self._detect_arch()
        self.epoch = epoch
        self.description = description
        self.summary = summary
        self.url = url
        self.location = location
        self.reponame = reponame
        self.base = base
        self._chksum_val = None
        self._chksum_type = None

    @staticmethod
    def _detect_arch():
        m = platform.machine().lower()
        if m in ("amd64", "x86_64", "i686", "i386"):
            return "x86_64"
        if m in ("aarch64", "arm64"):
            return "aarch64"
        return m

    @classmethod
    def from_archive(cls, archive_path, reponame=""):
        filename = os.path.basename(archive_path)
        name, ver_tuple, rc, arch = _parse_filename(filename)
        if not name:
            raise ValueError(f"Could not parse package name from '{filename}'")
        return cls(
            name=name,
            version=_fmt_version(ver_tuple),
            arch=arch or cls._detect_arch(),
            location=archive_path,
            reponame=reponame or (cls.CMDLINE_REPO if os.path.isfile(archive_path) else ""),
        )

    @classmethod
    def from_dict(cls, d):
        return cls(
            name=d.get("name", ""),
            version=d.get("version", "0"),
            release=d.get("release", "1"),
            arch=d.get("arch", ""),
            epoch=int(d.get("epoch", 0)),
            description=d.get("description", ""),
            summary=d.get("summary", ""),
            url=d.get("url", ""),
            location=d.get("location", ""),
            reponame=d.get("reponame", ""),
        )

    @property
    def evr(self):
        return f"{self.epoch}:{self.version}-{self.release}" if self.epoch else f"{self.version}-{self.release}"

    @property
    def nevra(self):
        return f"{self.name}-{self.evr}.{self.arch}"

    @property
    def from_system(self):
        return self.reponame == self.SYSTEM_REPO

    @property
    def from_cmdline(self):
        return self.reponame == self.CMDLINE_REPO

    @property
    def pkgtup(self):
        return (self.name, self.arch, self.epoch, self.version, self.release)

    @property
    def debug_name(self):
        if self.name.endswith(DEBUGINFO_SUFFIX):
            return self.name
        name = self.name
        if self.name.endswith(DEBUGSOURCE_SUFFIX):
            name = name[:-len(DEBUGSOURCE_SUFFIX)]
        return name + DEBUGINFO_SUFFIX

    @property
    def debugsource_name(self):
        return self.name + DEBUGSOURCE_SUFFIX

    @property
    def source_name(self):
        return self.name.rsplit("-", 2)[0] if "-" in self.name else self.name

    @property
    def chksum(self):
        return (self._chksum_type, self._chksum_val)

    @chksum.setter
    def chksum(self, val):
        self._chksum_type, self._chksum_val = val

    def evr_cmp(self, other):
        for a, b in zip(_parse_version(self.version), _parse_version(other.version)):
            if a != b:
                return -1 if a < b else 1
        return 0

    def evr_eq(self, other):
        return self.evr_cmp(other) == 0

    def evr_gt(self, other):
        return self.evr_cmp(other) > 0

    def evr_lt(self, other):
        return self.evr_cmp(other) < 0

    def __str__(self):
        return self.nevra

    def __repr__(self):
        return f"<Package {self.nevra}>"

    _ATTR_ALIASES = {"repo": "reponame"}

    def get(self, key, default=None):
        key = self._ATTR_ALIASES.get(key, key)
        return getattr(self, key, default)

    def __getitem__(self, key):
        val = self.get(key)
        if val is None:
            raise KeyError(key)
        return val

    def __contains__(self, key):
        return hasattr(self, key)

    def __hash__(self):
        return hash(self.pkgtup)

    def __eq__(self, other):
        if not isinstance(other, Package):
            return NotImplemented
        return self.pkgtup == other.pkgtup
