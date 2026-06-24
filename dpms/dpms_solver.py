"""APK-style dependency solver for DPMS.

The solver implements a forward-checking, deductive dependency resolution
algorithm similar to Alpine Linux's apk-tools. Key concepts:

  - Names are the unit of resolution (package names, virtual provides, etc.)
  - Each name has one or more providers (packages that can satisfy it)
  - A dependency constrains a name with an optional version match
  - The solver deductively assigns names to providers, propagating constraints
"""

from . import dpms_version as ver

DEBUG = False


# --- Solver flags ---
SOLVERF_LATEST = 1
SOLVERF_AVAILABLE = 2
SOLVERF_REINSTALL = 4
SOLVERF_INSTALLED = 8
SOLVERF_UPGRADE = 16
SOLVERF_REMOVE = 32
SOLVERF_IGNORE_CONFLICT = 64


# --- Version match operators ---
class VersionMatch:
    __slots__ = ('version', 'op')

    def __init__(self, version=None, op=ver.EQUAL):
        self.version = version
        self.op = op

    def satisfied_by(self, version_str):
        if self.version is None:
            return True
        if not version_str or version_str == '0':
            return False
        return ver.match(version_str, self.op, self.version)

    def __repr__(self):
        return f"VersionMatch({self.version}, op={self.op})"


# --- Dependency class ---
class Dependency:
    __slots__ = ('name', 'version_match', 'conflict')

    def __init__(self, name=None, version_match=None, conflict=False):
        self.name = name
        self.version_match = version_match
        self.conflict = conflict

    def __repr__(self):
        return f"Dependency({self.name}, {self.version_match}, conflict={self.conflict})"


# --- Provider class ---
class Provider:
    __slots__ = ('pkg', 'version_match')

    def __init__(self, pkg=None, version_match=None):
        self.pkg = pkg
        self.version_match = version_match

    def __repr__(self):
        return f"Provider({self.pkg}, {self.version_match})"


# --- Package state (solver-specific) ---
class PackageState:
    __slots__ = (
        'seen', 'error', 'pkg_selectable', 'pkg_available',
        'conflicts', 'dependencies_merged', 'dependencies_used',
        'iif_triggered', 'iif_failed', 'tag_ok', 'tag_preferred',
        'solver_flags', 'solver_flags_inheritable',
        'pinning_allowed', 'pinning_preferred',
    )

    def __init__(self):
        self.seen = False
        self.error = False
        self.pkg_selectable = True
        self.pkg_available = True
        self.conflicts = 0
        self.dependencies_merged = False
        self.dependencies_used = False
        self.iif_triggered = False
        self.iif_failed = False
        self.tag_ok = True
        self.tag_preferred = True
        self.solver_flags = 0
        self.solver_flags_inheritable = 0
        self.pinning_allowed = 0
        self.pinning_preferred = 0


# --- Name state (solver-specific) ---
class NameState:
    __slots__ = (
        'seen', 'locked', 'requirers', 'has_options',
        'has_auto_selectable', 'has_iif', 'no_iif',
        'reevaluate_deps', 'reevaluate_iif',
        'reverse_deps_done', 'chosen',
        'order_id',
    )

    def __init__(self):
        self.seen = False
        self.locked = False
        self.requirers = 0
        self.has_options = False
        self.has_auto_selectable = False
        self.has_iif = False
        self.no_iif = True
        self.reevaluate_deps = False
        self.reevaluate_iif = False
        self.reverse_deps_done = False
        self.chosen = Provider()
        self.order_id = 0


# --- Solver global state ---
class SolverState:
    __slots__ = (
        'world', 'dirty', 'unresolved', 'selectable', 'resolvenow',
        'errors', 'ignore_conflict', 'preferred_actions',
        'solver_flags_inherit', 'pinning_inherit',
        'allow_uninstall', 'allow_reinstall',
        'order_id',
    )

    def __init__(self, world=None):
        self.world = world or []
        self.dirty = []
        self.unresolved = []
        self.selectable = []
        self.resolvenow = []
        self.errors = 0
        self.ignore_conflict = False
        self.preferred_actions = set()
        self.solver_flags_inherit = 0
        self.pinning_inherit = 0
        self.allow_uninstall = True
        self.allow_reinstall = False
        self.order_id = 0


# =========================================================================
# Name / Package resolution helpers
# =========================================================================

def _provides_for_dep(providers, dep):
    """Check if any package in providers satisfies the dependency *dep*."""
    if dep.conflict:
        return False, None
    for p in providers:
        if _dep_is_provided(p, dep):
            return True, p.pkg
    return False, None


def _provides_for_dep_pkg(pkg, dep):
    """Check if *pkg* provides *dep* via its own name or provides."""
    if pkg is None:
        return False
    dep_name = dep.name.name if hasattr(dep.name, 'name') else str(dep.name)
    if dep_name == pkg.name:
        return dep.version_match is None or dep.version_match.satisfied_by(str(pkg.version))
    for prov_dep in getattr(pkg, 'provides', []):
        prov_name = prov_dep.name.name if hasattr(prov_dep.name, 'name') else str(prov_dep.name)
        if dep_name == prov_name:
            return dep.version_match is None or dep.version_match.satisfied_by(
                prov_dep.version_match.version if prov_dep.version_match else '0')
    return False


def _dep_is_provided(prov, dep):
    """Return True if *prov* (a Provider) satisfies *dep*."""
    if dep.conflict:
        return False
    pkg = prov.pkg
    if pkg is None:
        return False
    return _provides_for_dep_pkg(pkg, dep)


def _package_from_name(name):
    """Return the 'default' package for a name (the name itself as a package)."""
    pkg = Package()
    pkg.name = name.name if hasattr(name, 'name') else name
    pkg.version = '0'
    return pkg


# =========================================================================
# Name discovery
# =========================================================================

def _discover_name(name, ss, names):
    """Recursively discover *name* and all packages/dependencies it connects to."""
    if name.ss.seen:
        return
    name.ss.seen = True
    name.ss.no_iif = True

    # Mark all providers as seen
    for p in getattr(name, 'providers', []):
        pkg = p.pkg
        if pkg is None:
            continue
        if pkg.ss.seen:
            continue
        pkg.ss.seen = True
        pkg.ss.pinning_allowed = -1
        pkg.ss.pinning_preferred = -1
        pkg.ss.pkg_available = True
        pkg.ss.pkg_selectable = True

        # Recurse into package dependencies
        for dep in getattr(pkg, 'depends', []):
            _discover_name(dep.name, ss, names)

        # Track if all providers have iif_failed (no install_if triggers work)
        if pkg.ss.iif_failed:
            name.ss.no_iif = True
        else:
            name.ss.no_iif = False

    # Recurse into reverse install_if relationships
    for name0 in getattr(name, 'rinstall_if', []):
        _discover_name(name0, ss, names)

    # Recurse into provider provides
    for p in getattr(name, 'providers', []):
        pkg = p.pkg
        if pkg is None:
            continue
        for dep in getattr(pkg, 'provides', []):
            _discover_name(dep.name, ss, names)

    # Assign ordering
    ss.order_id += 1
    name.ss.order_id = ss.order_id

    for p in getattr(name, 'providers', []):
        for dep in getattr(p.pkg, 'install_if', []):
            _discover_name(dep.name, ss, names)


# =========================================================================
# Queue manipulation
# =========================================================================

def _lookup_name(names, name_or_str):
    """Look up a Name object from the names dict if given a string."""
    if isinstance(name_or_str, str):
        return names.get(name_or_str)
    return name_or_str


def _queue_dirty(name, ss):
    """Mark *name* for re-evaluation if it is not locked and has dependents."""
    if name.ss.locked:
        return
    if name.ss.requirers == 0 and not name.ss.reevaluate_iif:
        return
    if name not in ss.dirty:
        ss.dirty.append(name)


def _queue_unresolved(name, ss):
    """Classify *name* into the appropriate resolution queue."""
    if name.ss.locked:
        return
    if name.ss.requirers == 0 and not name.ss.has_iif and \
       not getattr(name, 'resolvenow', False) and not getattr(name, 'iif_needed', False):
        return

    # Remove from any existing queue
    if name in ss.unresolved:
        ss.unresolved.remove(name)
    if name in ss.selectable:
        ss.selectable.remove(name)
    if name in ss.resolvenow:
        ss.resolvenow.remove(name)

    if name.ss.reverse_deps_done and name.ss.requirers > 0 and \
       name.ss.has_auto_selectable and not name.ss.has_options:
        name.resolvenow = True
        ss.resolvenow.append(name)
    elif name.ss.has_auto_selectable:
        name.resolvenow = False
        ss.selectable.append(name)
    else:
        name.resolvenow = False
        ss.unresolved.append(name)


def _reevaluate_reverse_deps(name, ss, names):
    """Mark all reverse dependencies of *name* for re-evaluation."""
    for name0 in getattr(name, 'rdepends', []):
        name0 = _lookup_name(names, name0)
        if name0 is None or not name0.ss.seen:
            continue
        name0.ss.reevaluate_deps = True
        _queue_dirty(name0, ss)


def _reevaluate_reverse_installif(name, ss, names):
    """Mark all reverse install_if triggers of *name* for re-evaluation."""
    for name0 in getattr(name, 'rinstall_if', []):
        name0 = _lookup_name(names, name0)
        if name0 is None or not name0.ss.seen or name0.ss.no_iif:
            continue
        name0.ss.reevaluate_iif = True
        _queue_dirty(name0, ss)


# =========================================================================
# Package disqualification
# =========================================================================

def _disqualify_package(pkg, ss, names, reason=None):
    """Mark *pkg* as non-selectable and cascade the effects."""
    if reason and DEBUG:
        print(f"  DISQUALIFY {pkg.name} ({reason})")
    pkg.ss.pkg_selectable = False
    pkg_name = _lookup_name(names, pkg.name)
    if pkg_name:
        _reevaluate_reverse_deps(pkg_name, ss, names)
    for dep in getattr(pkg, 'provides', []):
        dep_name = _lookup_name(names, dep.name)
        if dep_name:
            _reevaluate_reverse_deps(dep_name, ss, names)
    if pkg_name:
        _reevaluate_reverse_installif(pkg_name, ss, names)
    for dep in getattr(pkg, 'provides', []):
        dep_name = _lookup_name(names, dep.name)
        if dep_name:
            _reevaluate_reverse_installif(dep_name, ss, names)


# =========================================================================
# Constraint application
# =========================================================================

def _apply_constraint(ppkg, dep, ss, names):
    """Apply dependency *dep* (from *ppkg*) - increments requirers and checks providers."""
    name = dep.name
    if dep.conflict and ss.ignore_conflict:
        return

    name.ss.requirers += 1
    if name.ss.requirers == 1:
        _queue_unresolved(name, ss)

    for p0 in getattr(name, 'providers', []):
        pkg0 = p0.pkg
        if pkg0 is None:
            continue
        is_provided = _dep_is_provided(p0, dep)
        if not is_provided:
            pkg0.ss.conflicts += 1
            if pkg0.ss.pkg_selectable:
                _disqualify_package(pkg0, ss, names, f"conflicts with {dep}")
        if is_provided:
            _inherit_pinning_and_flags(ppkg, pkg0, ss)


def _inherit_pinning_and_flags(ppkg, pkg, ss):
    """Copy solver flags and pinning from parent package to child."""
    if ppkg is not None:
        pkg.ss.solver_flags |= ppkg.ss.solver_flags_inheritable
        pkg.ss.solver_flags_inheritable |= ppkg.ss.solver_flags_inheritable
        pkg.ss.pinning_allowed |= ppkg.ss.pinning_allowed
    else:
        pkg.ss.solver_flags |= ss.solver_flags_inherit
        pkg.ss.solver_flags_inheritable |= ss.solver_flags_inherit
        pkg.ss.pinning_allowed |= ss.pinning_inherit
        pkg.ss.pinning_preferred = ss.pinning_inherit


def _name_requirers_changed(name, ss, names):
    """Called when *name*'s requirers count may have changed."""
    _queue_unresolved(name, ss)
    _reevaluate_reverse_installif(name, ss, names)
    _queue_dirty(name, ss)


# =========================================================================
# Reconsider (re-evaluate a name)
# =========================================================================

def _reconsider_name(name, ss, names):
    """Re-evaluate all providers of *name* and recompute option flags."""
    if DEBUG:
        print(f"reconsider: {name.name} (req={name.ss.requirers})")

    reevaluate_deps = name.ss.reevaluate_deps
    reevaluate_iif = name.ss.reevaluate_iif
    name.ss.reevaluate_deps = False
    name.ss.reevaluate_iif = False

    first_candidate = None
    num_options = 0
    num_tag_not_ok = 0
    has_iif = False
    no_iif = True
    has_auto_selectable = False

    for p in getattr(name, 'providers', []):
        pkg = p.pkg
        if pkg is None:
            continue
        pkg.ss.dependencies_merged = False

        if reevaluate_deps:
            if not pkg.ss.pkg_selectable:
                continue
            for dep in getattr(pkg, 'depends', []):
                if not _dependency_satisfiable(dep, ss, names):
                    _disqualify_package(pkg, ss, names, f"dep {dep.name} not satisfiable")
                    break

        if not pkg.ss.pkg_selectable:
            continue

        # Re-evaluate install_if triggers
        if reevaluate_iif and not pkg.ss.iif_triggered and not pkg.ss.iif_failed:
            pkg.ss.iif_triggered = True
            pkg.ss.iif_failed = False
            for dep in getattr(pkg, 'install_if', []):
                dname = _lookup_name(names, dep.name)
                if dname is None or not dname.ss.locked:
                    pkg.ss.iif_triggered = False
                    pkg.ss.iif_failed = False
                    if dep.conflict and dname is not None:
                        dname.iif_needed = True
                    if dname is not None:
                        _queue_unresolved(dname, ss)
                    break
                if not _dep_is_provided(dname.ss.chosen, dep):
                    pkg.ss.iif_triggered = False
                    pkg.ss.iif_failed = True
                    break

        has_iif |= pkg.ss.iif_triggered
        no_iif &= pkg.ss.iif_failed
        if pkg.ss.iif_triggered:
            has_auto_selectable = True

        if name.ss.requirers == 0:
            # No one requires this name, skip dependency merging
            continue

        pkg.ss.dependencies_merged = True
        if first_candidate is None:
            first_candidate = pkg

        if not pkg.ss.tag_ok:
            num_tag_not_ok += 1
        num_options += 1

    name.ss.has_options = num_options > 1 or num_tag_not_ok > 0
    name.ss.has_iif = has_iif
    name.ss.no_iif = no_iif
    name.ss.has_auto_selectable = has_auto_selectable

    # If only one candidate, immediately push its constraints
    if first_candidate is not None and num_options == 1:
        for dep in getattr(first_candidate, 'depends', []):
            _apply_constraint(first_candidate, dep, ss, names)

    # Determine if all reverse deps have been seen
    name.ss.reverse_deps_done = True
    for name0 in getattr(name, 'rdepends', []):
        name0 = _lookup_name(names, name0)
        if name0 and name0.ss.seen and not name0.ss.locked:
            name.ss.reverse_deps_done = False
            break

    _queue_unresolved(name, ss)


def _dependency_satisfiable(dep, ss, names):
    """Check if *dep* could still be satisfied by some provider."""
    name = _lookup_name(names, dep.name)
    if name is None:
        return False
    if dep.conflict and ss.ignore_conflict:
        return True
    if name.ss.locked:
        return _dep_is_provided(name.ss.chosen, dep)
    if name.ss.requirers == 0 and _dep_is_provided(Provider(), dep):
        return True
    for p in getattr(name, 'providers', []):
        if p.pkg and p.pkg.ss.pkg_selectable and _dep_is_provided(p, dep):
            return True
    return False


# =========================================================================
# Provider comparison
# =========================================================================

def _compare_providers(pA, pB, ss):
    """Compare two providers. Returns > 0 if pA is preferred over pB."""
    pkgA = pA.pkg
    pkgB = pB.pkg

    if pkgA is None and pkgB is None:
        return 0
    if pkgA is None:
        return -1
    if pkgB is None:
        return 1

    flags = pkgA.ss.solver_flags | pkgB.ss.solver_flags

    if flags & SOLVERF_LATEST:
        r = int(pkgA.ss.tag_ok) - int(pkgB.ss.tag_ok)
        if r:
            return r
    else:
        r = int(pkgA.ss.pkg_selectable) - int(pkgB.ss.pkg_selectable)
        if r:
            return r
        r = int(pkgA.ss.dependencies_used) - int(pkgB.ss.dependencies_used)
        if r:
            return r
        r = pkgB.ss.conflicts - pkgA.ss.conflicts
        if r:
            return r
        r = int(pkgA.ss.tag_ok) - int(pkgB.ss.tag_ok)
        if r:
            return r
        r = int(pkgA.ss.tag_preferred) - int(pkgB.ss.tag_preferred)
        if r:
            return r
        r = int(getattr(pkgA, 'ipkg', None) is not None) - \
            int(getattr(pkgB, 'ipkg', None) is not None)
        if r:
            return r

    # Compare by version
    va = getattr(pkgA, 'version', '0')
    vb = getattr(pkgB, 'version', '0')
    if isinstance(va, tuple):
        va = '.'.join(str(v) for v in va)
    if isinstance(vb, tuple):
        vb = '.'.join(str(v) for v in vb)
    cmp = ver.compare(str(va), str(vb))
    if cmp == ver.LESS:
        return -1
    if cmp == ver.GREATER:
        return 1

    # Prefer self-provider over name that matches via provides
    if pkgA.name == pkgB.name:
        cmp = ver.compare(str(getattr(pkgA, 'version', '0')),
                          str(getattr(pkgB, 'version', '0')))
        if cmp == ver.LESS:
            return -1
        if cmp == ver.GREATER:
            return 1

    # Provider priority
    r = getattr(pkgA, 'provider_priority', 0) - getattr(pkgB, 'provider_priority', 0)
    if r:
        return r

    # Prefer installed packages
    r = int(getattr(pkgA, 'ipkg', None) is not None) - \
        int(getattr(pkgB, 'ipkg', None) is not None)
    if r:
        return r

    # Prefer selectable
    r = int(pkgA.ss.pkg_selectable) - int(pkgB.ss.pkg_selectable)
    if r:
        return r

    return 0


# =========================================================================
# Package / Name assignment
# =========================================================================

def _assign_name(name, prov, ss, names):
    """Lock *name* to provider *prov* and disqualify conflicting providers."""
    if name.ss.locked:
        if prov.pkg is None and name.ss.chosen.pkg is None:
            return
        if ss.ignore_conflict:
            return
        # Both locked: conflict error
        if prov.pkg:
            prov.pkg.ss.error = True
            ss.errors += 1
        if name.ss.chosen.pkg:
            name.ss.chosen.pkg.ss.error = True
            ss.errors += 1
        return

    if DEBUG:
        if prov.pkg:
            print(f"  assign {name.name} -> {prov.pkg.name}-{prov.pkg.version if hasattr(prov.pkg, 'version') else '?'}")
        else:
            print(f"  assign {name.name} -> <none>")

    name.ss.locked = True
    name.ss.chosen = prov

    # Remove from all queues
    for qname in ('dirty', 'unresolved', 'selectable', 'resolvenow'):
        q = getattr(ss, qname)
        if name in q:
            q.remove(name)

    if not ss.ignore_conflict:
        for p0 in getattr(name, 'providers', []):
            p0pkg = p0.pkg
            if p0pkg == prov.pkg:
                continue
            if prov.pkg is None and p0.pkg is None:
                continue
            _disqualify_package(p0pkg, ss, names, "conflicting provides")

    _reevaluate_reverse_deps(name, ss, names)
    if prov.pkg:
        pkg_n = _lookup_name(names, prov.pkg.name)
        if pkg_n:
            _reevaluate_reverse_installif(pkg_n, ss, names)
        for d in getattr(prov.pkg, 'provides', []):
            d_n = _lookup_name(names, d.name)
            if d_n:
                _reevaluate_reverse_installif(d_n, ss, names)
    else:
        _reevaluate_reverse_installif(name, ss, names)


def _select_package(name, ss, names):
    """Select the best provider for *name* and lock it in."""
    if DEBUG:
        print(f"select_package: {name.name} (req={name.ss.requirers})")

    best = Provider()
    for p in getattr(name, 'providers', []):
        pkg = p.pkg
        if name.ss.requirers == 0 and not (pkg and pkg.ss.iif_triggered
                                            and pkg.ss.tag_ok and pkg.ss.pkg_selectable):
            continue
        if _compare_providers(p, best, ss) > 0:
            best = Provider(pkg, p.version_match)

    pkg = best.pkg
    if pkg:
        if not pkg.ss.pkg_selectable or not pkg.ss.tag_ok:
            pkg.ss.error = True
            ss.errors += 1
        pkg_name = _lookup_name(names, pkg.name)
        if pkg_name:
            _assign_name(pkg_name, Provider(pkg, best.version_match), ss, names)
        for d in getattr(pkg, 'provides', []):
            d_name = _lookup_name(names, d.name)
            if d_name:
                _assign_name(d_name, Provider(pkg, d.version_match), ss, names)
        for dep in getattr(pkg, 'depends', []):
            _apply_constraint(pkg, dep, ss, names)
    else:
        if DEBUG:
            print(f"  select_package: {name.name} [unassigned]")
        _assign_name(name, Provider(), ss, names)
        if name.ss.requirers > 0:
            if DEBUG:
                print(f"  ERROR: no provider for {name.name}")
            ss.errors += 1


def _dequeue_next_name(ss):
    """Return the next name to process from the priority queue."""
    if ss.resolvenow:
        return ss.resolvenow.pop(0)
    if ss.selectable:
        return ss.selectable.pop(0)
    if ss.unresolved:
        return ss.unresolved.pop(0)
    return None


# =========================================================================
# Public API
# =========================================================================

def solve(names, world=None, solver_flags=0):
    """Run the dependency solver.

    Parameters
    ----------
    names : dict or list
        A dict mapping name strings to Name objects, or a dict-like object.
        If a list, it is treated as a list of Name objects.

    world : list of Dependency, optional
        The 'world' dependencies (user-requested packages).

    solver_flags : int
        ORed SOLVERF_* flags.

    Returns
    -------
    errors : int
        Number of unresolved dependency errors.
    """
    ss = SolverState(world=world or [])
    ss.ignore_conflict = bool(solver_flags & SOLVERF_IGNORE_CONFLICT)

    # Convert to a dict of name -> Name
    if isinstance(names, list):
        names = {n.name: n for n in names}
    elif not isinstance(names, dict):
        # Assume it's a Sack-like object
        names = _build_name_index(names)

    # Initialize solver state for all Names
    for n in names.values():
        n.ss = NameState()

    # Initialize solver state for all Packages
    for name in names.values():
        for p in getattr(name, 'providers', []):
            if p.pkg is not None:
                p.pkg.ss = PackageState()

    # Process world dependencies
    if world:
        for dep in world:
            _discover_name(dep.name, ss, names)

        ss.solver_flags_inherit = solver_flags
        for dep in world:
            _apply_constraint(None, dep, ss, names)
        ss.solver_flags_inherit = 0

        # Main solve loop
        while True:
            while ss.dirty:
                name = ss.dirty.pop(0)
                _reconsider_name(name, ss, names)
            name = _dequeue_next_name(ss)
            if name is None:
                break
            _select_package(name, ss, names)

    return ss.errors


def _build_name_index(sack):
    """Build a name index from a Sack object."""
    from .dpms_package import Package

    result = {}

    class Name:
        def __init__(self, name):
            self.name = name
            self.providers = []
            self.rdepends = []
            self.rinstall_if = []
            self.ss = None

    for pkg in sack:
        if pkg.name not in result:
            result[pkg.name] = Name(pkg.name)

    def _name_ref(d):
        """Ensure dep.name is a Name object, creating one if needed."""
        if isinstance(d.name, str):
            if d.name not in result:
                result[d.name] = Name(d.name)
            d.name = result[d.name]
        return d.name

    for pkg in sack:
        name = result[pkg.name]
        # Add self-provider
        prov = Provider(pkg=pkg)
        name.providers.append(prov)

        # Add virtual provides
        for dep in getattr(pkg, 'provides', []):
            dname = _name_ref(dep)
            prov = Provider(pkg=pkg, version_match=dep.version_match)
            dname.providers.append(prov)
            # Track reverse dep
            if name not in dname.rdepends:
                dname.rdepends.append(name)

        # Track reverse deps from package dependencies
        for dep in getattr(pkg, 'depends', []):
            dname = _name_ref(dep)
            if name not in dname.rdepends:
                dname.rdepends.append(name)

        # Track install_if reverse links
        for dep in getattr(pkg, 'install_if', []):
            dname = _name_ref(dep)
            if name not in dname.rinstall_if:
                dname.rinstall_if.append(name)

    return result


# =========================================================================
# Changeset generation
# =========================================================================

def generate_changeset(names, installed_sack=None):
    """Generate a changeset from solver results.

    Parameters
    ----------
    names : dict
        Name index (name string -> Name object) with solver state.
    installed_sack : iterable, optional
        Currently installed packages.

    Returns
    -------
    to_install : list of Package
    to_remove : list of Package
    to_upgrade : list of (old_pkg, new_pkg)
    errors : list of str
    """
    to_install = []
    to_remove = []
    to_upgrade = []
    errors = []

    # Build a set of installed packages
    installed_map = {}
    if installed_sack:
        for pkg in installed_sack:
            installed_map[pkg.name] = pkg

    seen_packages = set()

    for name_str, name in names.items():
        if not name.ss.locked:
            continue
        if name.ss.chosen.pkg is None:
            continue

        pkg = name.ss.chosen.pkg
        if pkg in seen_packages:
            continue
        seen_packages.add(pkg)

        if pkg.ss.error:
            errors.append(f"Package {pkg.name} has errors")
            continue

        installed = installed_map.get(pkg.name)

        if installed is None:
            to_install.append(pkg)
        elif getattr(pkg, 'version', None) and \
             getattr(installed, 'version', None) and \
             _changeset_compare(pkg, installed) != 0:
            to_upgrade.append((installed, pkg))
        else:
            pass  # Already installed, no change

    # Find packages to remove (installed but not locked in solver)
    if installed_sack:
        for pkg in installed_sack:
            name = names.get(pkg.name)
            if name is None or not name.ss.locked or (name.ss.chosen.pkg is None):
                to_remove.append(pkg)

    return to_install, to_remove, to_upgrade, errors


def _changeset_compare(new_pkg, old_pkg):
    """Compare two packages for changeset purposes.  Returns <0, 0, >0."""
    v_new = str(getattr(new_pkg, 'version', '0'))
    v_old = str(getattr(old_pkg, 'version', '0'))
    return ver.compare(v_new, v_old)


# =========================================================================
# Convenience: high-level solve interface
# =========================================================================

def solve_from_sack(sack, world_deps=None, installed_sack=None, solver_flags=0):
    """Solve dependencies from a sack and generate changeset.

    Parameters
    ----------
    sack : Sack or iterable of Package
        All available packages.
    world_deps : list of Dependency, optional
        User-requested dependencies.  Each Dependency.name may be a string
        (package name) or a Name object.
    installed_sack : iterable of Package, optional
        Currently installed packages.
    solver_flags : int
        Solver flags.

    Returns
    -------
    changeset : tuple
        (to_install, to_remove, to_upgrade, errors) as returned by
        generate_changeset().
    """
    names = _build_name_index(sack)
    # Resolve string-based dependency names to Name objects
    resolved_world = []
    if world_deps:
        for dep in world_deps:
            dep_name = dep.name
            if isinstance(dep_name, str):
                dep_name = names.get(dep_name)
                if dep_name is None:
                    continue
            resolved_dep = Dependency(
                name=dep_name,
                version_match=dep.version_match,
                conflict=dep.conflict,
            )
            resolved_world.append(resolved_dep)
    errors = solve(names, world=resolved_world or None,
                   solver_flags=solver_flags)
    changeset = generate_changeset(names, installed_sack=installed_sack)
    return changeset
