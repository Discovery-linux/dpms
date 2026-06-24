from .dpms_pycomp import basestring


class Selector:
    def __init__(self, sack):
        self._sack = sack
        self._filters = {}

    def set(self, **kwargs):
        for key, value in kwargs.items():
            if isinstance(value, set):
                value = list(value)
            if key in ("name", "arch", "reponame", "version", "release", "nevra"):
                self._filters[key] = value
        return self

    def matches(self, pkg):
        for key, value in self._filters.items():
            attr = getattr(pkg, key, None)
            if attr is None:
                return False
            if isinstance(value, (list, tuple)):
                if attr not in value:
                    return False
            elif isinstance(value, basestring):
                if attr != value:
                    return False
            else:
                if attr != value:
                    return False
        return True

    def run(self):
        return [p for p in self._sack.iter_packages() if self.matches(p)]

    def __call__(self, **kwargs):
        if kwargs:
            self.set(**kwargs)
        return self.run()

    def __iter__(self):
        return iter(self.run())

    def __len__(self):
        return len(self.run())

    def __bool__(self):
        return len(self.run()) > 0
