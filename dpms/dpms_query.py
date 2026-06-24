import fnmatch
from .dpms_pycomp import basestring


class Query:
    def __init__(self, sack, flags=0):
        self._sack = sack
        self._flags = flags
        self._filters = []

    def clone(self):
        q = Query(self._sack, self._flags)
        q._filters = list(self._filters)
        return q

    def _match(self, pkg):
        for f in self._filters:
            if not f(pkg):
                return False
        return True

    # HACK: closures in a loop, but it works
    def filter(self, **kwargs):
        for key, value in kwargs.items():
            if key == "name":
                if isinstance(value, basestring):
                    pattern = value
                    self._filters.append(lambda p, pat=pattern: fnmatch.fnmatch(p.name, pat))
                else:
                    names = set(value)
                    self._filters.append(lambda p, ns=names: p.name in ns)
            elif key == "arch":
                arches = {value} if isinstance(value, basestring) else set(value)
                self._filters.append(lambda p, ar=arches: p.arch in ar)
            elif key == "reponame":
                self._filters.append(lambda p, r=value: p.reponame == r)
            elif key == "available":
                self._filters.append(lambda p: not p.from_system)
            elif key == "installed":
                self._filters.append(lambda p: p.from_system)
            elif key == "latest_per_arch":
                pass
            elif key == "empty":
                pass
            else:
                raise ValueError(f"Unsupported filter: {key}")
        return self

    def run(self):
        return [p for p in self._sack.iter_packages() if self._match(p)]

    def __call__(self, **kwargs):
        q = self.clone()
        return q.filter(**kwargs).run()

    def __iter__(self):
        return iter(self.run())
