import re

_KNOWN_ARCHES = [
    "x86_64", "amd64", "aarch64", "arm64", "armv7", "armv7hl",
    "armv7nhl", "armv8", "armv8l", "i686", "i386", "noarch", "src",
]
_ARCH_RE = re.compile(r"\.(" + "|".join(_KNOWN_ARCHES) + r")$")


def _parse_nevra(subject):
    arch = ""
    m = _ARCH_RE.search(subject)
    if m:
        arch = m.group(1)
        subject = subject[:m.start()]

    epoch = 0
    if ":" in subject:
        epoch_part, _, rest = subject.partition(":")
        try:
            epoch = int(epoch_part)
            subject = rest
        except ValueError:
            pass

    parts = subject.rsplit("-", 2)
    if len(parts) == 3 and re.match(r"^\d[\w.]*$", parts[2]):
        name, version, release = parts
    elif len(parts) >= 2 and re.match(r"^\d[\w.]*$", parts[-1]):
        name = parts[0]
        version = parts[1]
        release = ""
    else:
        return {"name": subject, "epoch": epoch, "version": "", "release": "", "arch": arch}

    return {
        "name": name,
        "epoch": epoch,
        "version": version,
        "release": release,
        "arch": arch,
    }


class Subject:
    def __init__(self, subject):
        self._subject = str(subject)
        self._parsed = _parse_nevra(self._subject)

    @property
    def nevra(self):
        return self._parsed

    def get_best_query(self, sack, with_nevra=True, with_provides=True):
        q = sack.query()
        if self._parsed and self._parsed.get("name"):
            q = q.filter(name=self._parsed["name"])
        elif self._subject:
            q = q.filter(name=self._subject)
        return q

    def get_best_selector(self, sack, with_nevra=True, with_provides=True):
        from .dpms_selector import Selector
        sel = Selector(sack)
        if self._parsed and self._parsed.get("name"):
            sel.set(name=self._parsed["name"])
        if self._parsed and self._parsed.get("arch"):
            sel.set(arch=self._parsed["arch"])
        if self._parsed and self._parsed.get("version"):
            sel.set(version=self._parsed["version"])
        return sel

    def __str__(self):
        return self._subject

    def __repr__(self):
        return f"<Subject '{self._subject}'>"
