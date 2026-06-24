# dpms_requester.py — port of zypper's SolverRequester.cc

import fnmatch
import re
from dataclasses import dataclass, field
from typing import Optional

from .dpms_package import _parse_version, _fmt_version
from .dpms_solver import (
    solve_from_sack, Dependency,
    SOLVERF_IGNORE_CONFLICT,
)
from . import dpms_core as core
from .dpms_query import Query

import logging
log = logging.getLogger("dpms:req")


# ── PackageSpec ─────────────────────────────────────────────────────

@dataclass
class PackageSpec:
    orig_str: str = ""
    parsed_cap: str = ""
    repo_alias: str = ""
    version_str: str = ""
    arch_str: str = ""
    modified: bool = False  # True if prefixed with +/-

    @classmethod
    def parse(cls, raw):
        s = cls(orig_str=raw, parsed_cap=raw)
        if raw.startswith('+'):
            s.modified = True
            raw = raw[1:]
            s.orig_str = raw
            s.parsed_cap = raw
        elif raw.startswith('-'):
            s.modified = "-"
            raw = raw[1:]
            s.orig_str = raw
            s.parsed_cap = raw
        if ':' in raw and not raw.startswith('^'):
            parts = raw.split(':', 1)
            s.repo_alias = parts[0]
            s.parsed_cap = parts[1]
        return s


# ── PackageArgs ─────────────────────────────────────────────────────

@dataclass
class PackageArgs:
    """Collection of PackageSpec with +/- syntax."""
    _items: list = field(default_factory=list)

    def add(self, spec):
        self._items.append(spec)

    def dos(self):
        return [s for s in self._items if s.modified != "-"]

    def donts(self):
        return [s for s in self._items if s.modified == "-"]

    def empty(self):
        return len(self._items) == 0

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        return iter(self._items)


# ── Feedback IDs ────────────────────────────────────────────────────

class Feedback:
    ALREADY_INSTALLED = "already_installed"
    NOT_IN_REPOS = "not_in_repos"
    NOT_INSTALLED = "not_installed"
    NOT_FOUND_NAME = "not_found_name"
    NOT_FOUND_NAME_TRYING_CAPS = "not_found_name_trying_caps"
    NOT_FOUND_CAP = "not_found_cap"
    NO_INSTALLED_PROVIDER = "no_installed_provider"
    SELECTED_IS_OLDER = "selected_is_older"
    FORCED_INSTALL = "forced_install"
    SET_TO_INSTALL = "set_to_install"
    SET_TO_REMOVE = "set_to_remove"
    ADDED_REQUIREMENT = "added_requirement"
    ADDED_CONFLICT = "added_conflict"
    INSTALLED_LOCKED = "installed_locked"
    NO_UPD_CANDIDATE = "no_upd_candidate"
    UPD_CANDIDATE_USER_RESTRICTED = "upd_candidate_user_restricted"
    UPD_CANDIDATE_IS_LOCKED = "upd_candidate_is_locked"
    UPD_CANDIDATE_CHANGES_VENDOR = "upd_candidate_changes_vendor"
    UPD_CANDIDATE_HAS_LOWER_PRIO = "upd_candidate_has_lower_prio"
    PATCH_UNWANTED = "patch_unwanted"
    PATCH_OPTIONAL = "patch_optional"
    PATCH_INTERACTIVE_SKIPPED = "patch_interactive_skipped"
    PATCH_TOO_NEW = "patch_too_new"
    PATCH_WRONG_CAT = "patch_wrong_cat"
    PATCH_WRONG_SEV = "patch_wrong_sev"
    PATCH_NOT_NEEDED = "patch_not_needed"
    INVALID_REQUEST = "invalid_request"

    @dataclass
    class Entry:
        id: str = ""
        pkg_spec: Optional[PackageSpec] = None
        selected: Optional[object] = None
        installed: Optional[object] = None
        hint: str = ""

    def __init__(self):
        self._entries = []

    def add(self, fb_id, pkg_spec=None, selected=None, installed=None, hint=""):
        self._entries.append(self.Entry(fb_id, pkg_spec, selected, installed, hint))

    def has(self, fb_id):
        return any(e.id == fb_id for e in self._entries)

    def __iter__(self):
        return iter(self._entries)


# ── PoolItemBest ────────────────────────────────────────────────────

class PoolItemBest:
    """Simplified version of zypper's PoolItemBest — find best-matching packages."""

    def __init__(self, items, prefer_not_locked=True):
        self._items = list(items)
        self._prefer_not_locked = prefer_not_locked

    def empty(self):
        return len(self._items) == 0

    def __iter__(self):
        return iter(self._items)

    def begin(self):
        return iter(self._items)

    def end(self):
        return iter([])


# ── ciMatchHint (case-insensitive match hint) ───────────────────────

def _get_ci_match_hint(query_result):
    """Return a hint string of case-insensitive matches."""
    names = []
    for item in query_result[:3]:
        name = item.name if hasattr(item, 'name') else str(item)
        names.append(name)
    hint = ", ".join(names)
    if len(query_result) > 3:
        hint += ",..."
    return hint


# ── Selectable (wrapper around package name) ────────────────────────

class Selectable:
    """Mimics zypper's ui::Selectable for a given package name."""

    def __init__(self, name, sack=None, installed_sack=None):
        self.name = name
        self._sack = sack or []
        self._installed_sack = installed_sack or []
        self._installed = None
        self._available = []
        self._candidate = None

        # populate from sacks
        for pkg in (self._installed_sack if self._installed_sack else []):
            if pkg.name == name:
                self._installed = pkg

        for pkg in (self._sack if self._sack else []):
            if pkg.name == name and pkg != self._installed:
                self._available.append(pkg)

        # sort available by version desc
        self._available.sort(key=lambda p: _parse_version(p.version), reverse=True)

    def installed_obj(self):
        return self._installed

    def available_empty(self):
        return len(self._available) == 0

    def available_begin(self):
        return iter(self._available)

    def available_end(self):
        return iter([])

    def highest_available_version_obj(self):
        return self._available[0] if self._available else None

    def update_candidate_obj(self):
        """Best candidate for update (highest version not restricted)."""
        if self._candidate:
            return self._candidate
        return self.highest_available_version_obj()

    def set_on_system(self, pi, status):
        """Mark a PoolItem as 'to be installed' (USER request)."""
        log.debug(f"Selectable.set_on_system: {pi}")

    @property
    def kind(self):
        return "package"

    def has_locks(self):
        return False

    @property
    def status(self):
        return "unknown"


def as_selectable(item):
    """Turn a PoolItem into a Selectable."""
    return Selectable(item.name, [])


# ── SolverRequester::Options ────────────────────────────────────────

@dataclass
class RequesterOptions:
    force: bool = False
    oldpackage: bool = False
    best_effort: bool = False
    force_by_cap: bool = False
    force_by_name: bool = True
    from_repos: list = field(default_factory=list)
    allow_vendor_change: bool = True
    skip_optional_patches: bool = False
    skip_interactive: bool = False
    cli_match_patch: dict = field(default_factory=dict)

    def set_force_by_cap(self, value):
        if value and self.force_by_name:
            log.debug("resetting previously set force_by_name")
        self.force_by_cap = value
        self.force_by_name = not self.force_by_cap

    def set_force_by_name(self, value):
        if value and self.force_by_cap:
            log.debug("resetting previously set force_by_cap")
        self.force_by_name = value
        self.force_by_cap = not self.force_by_name


# ── SolverRequester ─────────────────────────────────────────────────

class SolverRequester:
    """Port of zypper's SolverRequester. Handles install/remove/update requests."""

    def __init__(self, sack=None, installed_sack=None, opts=None):
        self._sack = sack
        self._installed_sack = installed_sack or []
        self._opts = opts or RequesterOptions()
        self._command = "install"
        self._feedback = Feedback()
        self._to_install = []
        self._to_remove = []
        self._requests = []
        self._conflicts = []

    # ── public entry points ──

    def install(self, args):
        self._command = "install"
        self._install_remove(args)

    def remove(self, args):
        self._command = "remove"
        if any(getattr(s, 'do_by_default', False) for s in args):
            log.error("PackageArgs::Options::do_by_default == True. "
                      "Set it to 'false' when doing 'remove'")
            return
        self._install_remove(args)

    def update(self, args):
        self._command = "update"
        for spec in args.dos():
            self._install_spec(spec)

    def _install_remove(self, args):
        if args.empty():
            return
        for spec in args.dos():
            self._install_spec(spec)
        for spec in args.donts():
            self._remove_spec(spec)

    # ── install spec ──

    def _install_spec(self, pkg):
        """Port of SolverRequester::install(const PackageSpec&)."""
        ci_match_hint = ""

        # first try by name
        if not self._opts.force_by_cap:
            query = self._query_by_name(pkg)

            # get best matching items
            best_matches = PoolItemBest(query, prefer_not_locked=True)

            if not best_matches.empty():
                not_installed = 0
                seen_names = set()
                for item in best_matches:
                    if item.name in seen_names:
                        continue
                    seen_names.add(item.name)
                    sel = Selectable(item.name, self._sack or [], self._installed_sack or [])
                    instobj = sel.installed_obj()
                    if instobj:
                        if sel.available_empty():
                            if not self._opts.force:
                                self._feedback.add(Feedback.ALREADY_INSTALLED, pkg,
                                                   instobj, instobj)
                            self._feedback.add(Feedback.NOT_IN_REPOS, pkg,
                                               instobj, instobj)
                            log.info(f"{sel.name} not in repos, can't (re)install")
                            return

                        user_constraints = (
                            bool(pkg.version_str)
                            or bool(pkg.arch_str)
                            or bool(self._opts.from_repos)
                            or bool(pkg.repo_alias)
                        )
                        changes_vendor = False  # simplified

                        best = sel.update_candidate_obj()
                        if best and hasattr(best, 'status') and best.status.is_locked():
                            best = None

                        if user_constraints:
                            self._update_to(pkg, item)
                        elif self._opts.force:
                            self._update_to(pkg, sel.highest_available_version_obj())
                        elif best:
                            self._update_to(pkg, best)
                        elif changes_vendor and not self._opts.allow_vendor_change:
                            self._update_to(pkg, instobj)
                        else:
                            self._update_to(pkg, item)
                    elif self._command == "install":
                        self._set_to_install(item)
                        log.info(f"installing {item}")
                    else:
                        not_installed += 1

                if not_installed == len(list(best_matches)):
                    self._feedback.add(Feedback.NOT_INSTALLED, pkg)
                return
            elif self._opts.force_by_name or (pkg.modified and pkg.modified != "-"):
                self._feedback.add(Feedback.NOT_FOUND_NAME, pkg)
                log.warning(f"{pkg} not found")
                return

            self._feedback.add(Feedback.NOT_FOUND_NAME_TRYING_CAPS, pkg)
            ci_match_hint = _get_ci_match_hint(query)

        # try by capability
        providers = self._get_providers(pkg.parsed_cap)
        if not providers:
            self._feedback.add(Feedback.NOT_FOUND_CAP, pkg, hint=ci_match_hint)
            log.warning(f"{pkg} not found")
            return

        installed_providers = self._get_installed_providers(pkg.parsed_cap)
        for prov in installed_providers:
            if self._command == "install":
                self._feedback.add(Feedback.ALREADY_INSTALLED, pkg, prov, prov)
            log.info(f"provider '{prov}' of '{pkg.parsed_cap}' installed")

        if not installed_providers:
            log.debug(f"adding requirement {pkg.parsed_cap}")
            self._add_requirement(pkg)

    # ── remove spec ──

    def _remove_spec(self, pkg):
        """Port of SolverRequester::remove(const PackageSpec&)."""
        ci_match_hint = ""

        if not self._opts.force_by_cap:
            query = self._query_by_name(pkg)
            if query:
                got_installed = False
                for item in query:
                    if getattr(item, 'status', None) and item.status == "installed":
                        log.debug(f"Marking for deletion: {item}")
                        self._set_to_remove(item)
                        got_installed = True
                if got_installed:
                    return
                else:
                    self._feedback.add(Feedback.NOT_INSTALLED, pkg)
                    log.info(f"'{pkg.parsed_cap}' is not installed")
                    if self._opts.force_by_name:
                        return
            elif self._opts.force_by_name or (pkg.modified and pkg.modified != "-"):
                self._feedback.add(Feedback.NOT_FOUND_NAME, pkg)
                log.warning(f"{pkg} not found")
                return

            self._feedback.add(Feedback.NOT_FOUND_NAME_TRYING_CAPS, pkg)
            ci_match_hint = _get_ci_match_hint(query)

        providers = self._get_providers(pkg.parsed_cap)
        if not providers:
            self._feedback.add(Feedback.NOT_FOUND_CAP, pkg, hint=ci_match_hint)
            log.warning(f"{pkg} not found")
            return

        installed_providers = self._get_installed_providers(pkg.parsed_cap)
        if not installed_providers:
            self._feedback.add(Feedback.NO_INSTALLED_PROVIDER, pkg)
            log.info(f"no provider of {pkg.parsed_cap} is installed")
        else:
            log.info(f"adding conflict {pkg.parsed_cap}")
            self._add_conflict(pkg)

    # ── helpers ──

    def _query_by_name(self, pkg):
        """Query sack+installed for packages matching pkg name, using glob."""
        results = []
        if self._sack:
            q = Query(self._sack)
            q.filter(name=pkg.parsed_cap)
            results.extend(q.run())
        if self._installed_sack:
            for p in self._installed_sack:
                if fnmatch.fnmatch(p.name, pkg.parsed_cap):
                    p.status = "installed"
                    results.append(p)
        return results

    def _get_providers(self, cap):
        """Find packages that provide *cap*."""
        providers = []
        seen = set()
        for source in (self._sack, self._installed_sack):
            if not source:
                continue
            for pkg in source:
                if id(pkg) in seen:
                    continue
                seen.add(id(pkg))
                if fnmatch.fnmatch(pkg.name, cap):
                    providers.append(pkg)
                    continue
                for prov in getattr(pkg, 'provides', []):
                    prov_name = prov if isinstance(prov, str) else getattr(prov, 'name', str(prov))
                    if fnmatch.fnmatch(prov_name, cap):
                        providers.append(pkg)
                        break
        return providers

    def _get_installed_providers(self, cap):
        """Find installed packages that provide *cap*."""
        providers = []
        for pkg in self._installed_sack:
            if fnmatch.fnmatch(pkg.name, cap):
                providers.append(pkg)
            for prov in getattr(pkg, 'provides', []):
                prov_name = prov if isinstance(prov, str) else getattr(prov, 'name', str(prov))
                if fnmatch.fnmatch(prov_name, cap):
                    providers.append(pkg)
        return providers

    def _update_to(self, pkg, selected):
        """Port of SolverRequester::updateTo()."""
        if selected is None:
            log.error("Candidate is empty, returning!")
            return

        # find selectable for this package
        sel = Selectable(selected.name, self._sack or [], self._installed_sack or [])
        theone = sel.update_candidate_obj()
        installed = sel.installed_obj()
        highest = sel.highest_available_version_obj()

        if not installed:
            log.error("no installed object, nothing to update, returning")
            return

        log.debug(f"selected:  {selected}")
        log.debug(f"best:      {theone}")
        log.debug(f"highest:   {highest}")
        log.debug(f"installed: {installed}")

        # determine action
        action = True
        if not self._identical(installed, selected) or self._opts.force:
            if self._opts.best_effort:
                req = f"{sel.name} > {installed.version}"
                self._add_requirement(PackageSpec(orig_str=req, parsed_cap=req))
                log.info(f"{sel.name} update: adding requirement {req}")
            elif self._version_gt(selected, installed):
                self._set_to_install(selected)
                log.info(f"{sel.name} update: setting {selected} to install")
            elif (self._version_eq(selected, installed)
                  and selected.arch != installed.arch
                  and pkg.arch_str):
                self._set_to_install(selected)
                log.info(f"{sel.name} update: setting {selected} to install (arch change)")
            elif (self._version_eq(selected, installed)
                  and pkg.repo_alias):
                self._set_to_install(selected)
                log.info(f"{sel.name} update: setting {selected} to install (repo change)")
            elif self._opts.force or self._opts.oldpackage:
                self._set_to_install(selected)
                log.info(f"{sel.name} update: forced setting {selected} to install")
            else:
                action = False
        else:
            action = False

        # reporting
        if self._identical(installed, selected) or (not action and self._version_eq(installed, selected)):
            if self._opts.force:
                return
            if self._command == "install":
                self._feedback.add(Feedback.ALREADY_INSTALLED, pkg, selected, installed)
                log.info(f"'{pkg.parsed_cap}' already installed")
            if sel.available_empty():
                self._feedback.add(Feedback.NO_UPD_CANDIDATE, pkg, None, installed)
                log.debug(f"no available objects in repos, skipping update of {sel.name}")
                return
            if self._identical(installed, highest) or self._version_le(highest, installed):
                self._feedback.add(Feedback.NO_UPD_CANDIDATE, pkg, selected, installed)
        elif self._version_gt(installed, selected):
            if self._opts.force or self._opts.oldpackage:
                return
            self._feedback.add(Feedback.SELECTED_IS_OLDER, pkg, selected, installed)
            log.info("Selected is older than the installed. "
                     "Will not downgrade unless --oldpackage is used")

        # newer version available but restricted
        if (highest
            and not self._identical(selected, highest)
            and self._version_gt(highest, installed)):
            user_constraints = (
                bool(pkg.version_str)
                or bool(pkg.arch_str)
                or bool(self._opts.from_repos)
                or bool(pkg.repo_alias)
            )
            if user_constraints:
                self._feedback.add(Feedback.UPD_CANDIDATE_USER_RESTRICTED, pkg,
                                   selected, installed)
                log.debug(f"Newer object exists, but constrained: {highest}")

    def _set_to_install(self, pi):
        if self._opts.force:
            self._feedback.add(Feedback.FORCED_INSTALL)
            self._to_install.append(pi)
            return
        sel = Selectable(pi.name, self._sack or [], self._installed_sack or [])
        if sel.has_locks():
            cap = f"{pi.name}-{pi.version}"
            self._requests.append(("require", cap))
            self._feedback.add(Feedback.SET_TO_INSTALL)
            self._feedback.add(Feedback.INSTALLED_LOCKED)
            return
        sel.set_on_system(pi, "user")
        self._feedback.add(Feedback.SET_TO_INSTALL)
        self._to_install.append(pi)

    def _set_to_remove(self, pi):
        sel = Selectable(pi.name, self._sack or [], self._installed_sack or [])
        if sel.has_locks():
            cap = f"{pi.name}-{pi.version}"
            self._conflicts.append(cap)
            self._feedback.add(Feedback.SET_TO_REMOVE)
            self._feedback.add(Feedback.INSTALLED_LOCKED)
            return
        self._feedback.add(Feedback.SET_TO_REMOVE)
        self._to_remove.append(pi)

    def _add_requirement(self, pkg):
        cap = pkg.parsed_cap
        self._requests.append(("require", cap))
        self._feedback.add(Feedback.ADDED_REQUIREMENT, pkg)

    def _add_conflict(self, pkg):
        cap = pkg.parsed_cap
        self._conflicts.append(cap)
        self._feedback.add(Feedback.ADDED_CONFLICT, pkg)

    # ── version comparison helpers ──

    @staticmethod
    def _identical(a, b):
        if a is None or b is None:
            return False
        return (a.name == b.name
                and str(a.version) == str(b.version)
                and a.arch == b.arch)

    @staticmethod
    def _version_gt(a, b):
        va = _parse_version(str(a.version))
        vb = _parse_version(str(b.version))
        return va > vb

    @staticmethod
    def _version_eq(a, b):
        return str(a.version) == str(b.version)

    @staticmethod
    def _version_le(a, b):
        va = _parse_version(str(a.version))
        vb = _parse_version(str(b.version))
        return va <= vb

    # ── results ──

    def get_result(self):
        return self._to_install, self._to_remove, self._requests, self._conflicts

    def feedback(self):
        return self._feedback
