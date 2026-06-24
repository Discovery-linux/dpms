import glob
import importlib
import logging
import os
import sys
import traceback

logger = logging.getLogger("dpms")

PLUGIN_PACKAGE = "dpms.dpms_plugin.dynamic"


class Plugin:
    name = "<invalid>"

    def __init__(self, base, cli=None):
        self.base = base
        self.cli = cli

    def pre_config(self):
        pass

    def config(self):
        pass

    def resolved(self):
        pass

    def sack(self):
        pass

    def pre_transaction(self):
        pass

    def transaction(self):
        pass


class Plugins:
    def __init__(self):
        self.plugin_cls = []
        self.plugins = []

    def _caller(self, method):
        for plugin in self.plugins:
            try:
                getattr(plugin, method)()
            except Exception:
                logger.error(traceback.format_exc())

    def load(self, plugin_paths, disable_plugins=None, enable_plugins=None):
        disable_plugins = set(disable_plugins or [])
        enable_plugins = set(enable_plugins or [])

        if PLUGIN_PACKAGE in sys.modules:
            raise RuntimeError("load() called twice")

        import types
        package = types.ModuleType(PLUGIN_PACKAGE)
        package.__path__ = []
        package.__file__ = None
        sys.modules[PLUGIN_PACKAGE] = package

        files = []
        for p in plugin_paths:
            files.extend(glob.glob(os.path.join(p, "*.py")))

        matched = []
        for fn in files:
            plugin_name = os.path.splitext(os.path.basename(fn))[0]
            if _should_load(plugin_name, disable_plugins, enable_plugins):
                path, module = os.path.split(fn)
                package.__path__.append(path)
                mod_name, _ = os.path.splitext(module)
                full_name = f"{PLUGIN_PACKAGE}.{mod_name}"
                try:
                    importlib.import_module(full_name)
                    matched.append(fn)
                except Exception as e:
                    logger.error(f"Failed loading plugin '{mod_name}': {e}")

        self.plugin_cls = Plugin.__subclasses__()[:]
        if self.plugin_cls:
            names = sorted(p.name for p in self.plugin_cls)
            logger.debug(f"Loaded plugins: {', '.join(names)}")

    def init(self, base, cli=None):
        for p_cls in self.plugin_cls:
            self.plugins.append(p_cls(base, cli))

    def run(self, method):
        self._caller(method)

    def unload(self):
        if PLUGIN_PACKAGE in sys.modules:
            del sys.modules[PLUGIN_PACKAGE]
            self.plugin_cls.clear()
            self.plugins.clear()


def _should_load(plugin_name, disable_plugins, enable_plugins):
    if not enable_plugins and not disable_plugins:
        return True
    if any(_match(p, plugin_name) for p in disable_plugins):
        return any(_match(p, plugin_name) for p in enable_plugins)
    if enable_plugins:
        return any(_match(p, plugin_name) for p in enable_plugins)
    return True


def _match(pattern, name):
    import fnmatch
    return any(fnmatch.fnmatch(name, alt)
               for alt in {name, name.replace("_", "-")})
