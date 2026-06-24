# dpms_commit.py — zypper-style solve & commit pipeline for DPMS

import os
from dataclasses import dataclass, field
from typing import Optional

from rich.table import Table
from rich.console import Console
from rich import print as rprint
from rich.prompt import Confirm

from . import config
from . import dpms_core as core
from . import dpms_logging
from .dpms_package import Package
from .dpms_progress import ProgressStages

log = dpms_logging.get_logger("dpms")
console = Console()


# ── CommitPolicy ────────────────────────────────────────────────────

@dataclass
class CommitPolicy:
    dry_run: bool = False
    force_resolution: bool = False
    no_recommends: bool = False
    allow_downgrade: bool = False


# ── Summary ─────────────────────────────────────────────────────────

@dataclass
class Summary:
    to_install: list = field(default_factory=list)
    to_remove: list = field(default_factory=list)
    to_upgrade: list = field(default_factory=list)
    to_download: int = 0
    total_size: str = "0 B"

    @property
    def has_changes(self):
        return bool(self.to_install or self.to_remove or self.to_upgrade)

    def show(self, show_version=False, show_arch=False, show_repo=False,
             show_vendor=False, details=False, page=False):
        if not self.has_changes:
            rprint("[yellow]Nothing to do.[/yellow]")
            return
        table = Table(title="Package Changes", title_style="bold blue")
        table.add_column("Action", style="bold")
        table.add_column("Package")
        if show_version:
            table.add_column("Version", no_wrap=True)
        if show_arch:
            table.add_column("Arch")
        if show_repo:
            table.add_column("Repo")
        if show_vendor:
            table.add_column("Vendor")

        for pkg in self.to_install:
            row = ["[green]install[/green]", pkg.get("name", "?")]
            if show_version:
                row.append(pkg.get("version", ""))
            if show_arch:
                row.append(pkg.get("arch", core.DPMS_ARCH))
            if show_repo:
                row.append(pkg.get("repo", "?"))
            if show_vendor:
                row.append(pkg.get("vendor", "dpms"))
            table.add_row(*row)

        for pkg in self.to_remove:
            row = ["[red]remove[/red]", pkg.get("name", "?")]
            if show_version:
                row.append(pkg.get("version", ""))
            if show_arch:
                row.append(pkg.get("arch", ""))
            if show_repo:
                row.append("")
            if show_vendor:
                row.append("")
            table.add_row(*row)

        for old, new in self.to_upgrade:
            row = ["[yellow]upgrade[/yellow]",
                   old.get("name", "?"),
                   f"{old.get('version', '?')} -> {new.get('version', '?')}"]
            if show_arch:
                row.append(new.get("arch", core.DPMS_ARCH))
            if show_repo:
                row.append(new.get("repo", "?"))
            if show_vendor:
                row.append(new.get("vendor", "dpms"))
            table.add_row(*row)

        console.print(table)
        rprint(f"[dim]Total: {len(self.to_install)} to install, "
               f"{len(self.to_remove)} to remove, "
               f"{len(self.to_upgrade)} to upgrade[/dim]")


# ── Locked packages ─────────────────────────────────────────────────

LOCK_FILE = os.path.join(config.DP_DB_DIR, ".locked")

def _load_locks():
    if not os.path.exists(LOCK_FILE):
        return set()
    with open(LOCK_FILE) as f:
        return set(line.strip() for line in f if line.strip())

def _save_locks(locks):
    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
    with open(LOCK_FILE, 'w') as f:
        for pkg in sorted(locks):
            f.write(pkg + '\n')

def lock_package(name):
    locks = _load_locks()
    locks.add(name)
    _save_locks(locks)
    rprint(f"[green]Locked[/green] {name}")

def unlock_package(name):
    locks = _load_locks()
    locks.discard(name)
    _save_locks(locks)
    rprint(f"[green]Unlocked[/green] {name}")

def list_locked():
    locks = _load_locks()
    if not locks:
        rprint("[yellow]No locked packages.[/yellow]")
        return
    rprint("[bold]Locked packages:[/bold]")
    for pkg in sorted(locks):
        rprint(f"  [cyan]{pkg}[/cyan]")


# ── Repo priority ───────────────────────────────────────────────────

def set_repo_priority(name, priority):
    repos = core.load_repo_list()
    if name not in repos:
        rprint(f"[red]Repository '{name}' not found.[/red]")
        return
    repos[name]["priority"] = priority
    core.save_repo_list(repos)
    rprint(f"[green]Set priority[/green] {priority} [green]for[/green] {name}")


def list_repo_priorities():
    repos = core.load_repo_list()
    if not repos:
        rprint("[yellow]No repositories configured.[/yellow]")
        return
    table = Table(title="Repo Priorities")
    table.add_column("Repo", style="bold green")
    table.add_column("Priority", style="cyan")
    table.add_column("Arch")
    for name, info in sorted(repos.items(),
                             key=lambda x: x[1].get("priority", 99)):
        prio = info.get("priority", 99)
        arch = info.get("arch") or "any"
        table.add_row(name, str(prio), arch)
    console.print(table)


# ── Solver problem display (like zypper show_problems) ──────────────

def show_problems(errors, installed_map, sack):
    """Interactive dependency problem resolution.
    Returns True if user wants to retry, False to cancel.
    """
    if not errors:
        return True

    rprint(f"\n[bold red]Dependency problems:[/bold red] {len(errors)}")

    for i, err in enumerate(errors, 1):
        rprint(f"\n[bold yellow]Problem {i}:[/bold yellow] {err}")

    rprint("\n[dim]Options:[/dim]")
    rprint("  [bold]1[/bold] — Force resolution (ignore conflicts)")
    rprint("  [bold]2[/bold] — Show details")
    rprint("  [bold]r[/bold] — Retry solving")
    rprint("  [bold]c[/bold] — Cancel")

    choice = input("[?] Choose: ").strip().lower()

    if choice == '1':
        policy = CommitPolicy(force_resolution=True)
        return policy
    elif choice == '2':
        for i, err in enumerate(errors, 1):
            rprint(f"[dim]  {i}: {err}[/dim]")
        return show_problems(errors, installed_map, sack)
    elif choice == 'r':
        return CommitPolicy()
    else:
        return None  # cancel


# ── Summary prompt (like zypper's Continue? prompt) ─────────────────

def prompt_summary(summary, policy):
    """Interactive summary prompt.  Returns True to commit, False to cancel."""
    if not summary.has_changes or policy.dry_run:
        return True  # no prompt needed for dry-run

    show_opts = {
        'v': ('Version', lambda: summary.show(show_version=True)),
        'a': ('Arch', lambda: summary.show(show_arch=True)),
        'r': ('Repo', lambda: summary.show(show_repo=True)),
        'd': ('Details', lambda: summary.show(details=True)),
    }
    opt_help = ' / '.join(f"[bold]{k}[/bold]={v[0]}" for k, v in show_opts.items())

    while True:
        rprint()
        rprint(f"[yellow]Continue?[/yellow] ({opt_help} / [bold]n[/bold]=no)")
        choice = input("> ").strip().lower()
        if choice == '' or choice == 'y':
            return True
        if choice in show_opts:
            show_opts[choice][1]()
            continue
        if choice == 'n':
            rprint("[red]Cancelled.[/red]")
            return False
        rprint("[red]Invalid choice.[/red]")


# ── resolve() — wraps dpms_solver ───────────────────────────────────

def resolve(policy, packages=None):
    """Run the dependency solver and return (Summary, errors)."""
    sack = None
    world_deps = None
    if packages:
        from .dpms_solver import Dependency
        world_deps = [Dependency(name=p) for p in packages]

    locked = _load_locks()

    solver_flags = 0
    from .dpms_solver import (
        SOLVERF_UPGRADE, SOLVERF_REINSTALL, SOLVERF_REMOVE,
        SOLVERF_IGNORE_CONFLICT,
    )
    if policy.force_resolution:
        solver_flags |= SOLVERF_IGNORE_CONFLICT

    errors = []
    to_install = []
    to_remove = []
    to_upgrade = []

    # try using the sack solver
    try:
        from .dpms_sack import Sack
        from .dpms_repo import Repo
        from .dpms_solver import solve_from_sack
        sack = Sack()
        repo = Repo(name="default")
        sack.load_repo(repo)
        installed_pkgs = []
        db_dir = core.DP_DB_DIR
        if os.path.exists(db_dir):
            for name in os.listdir(db_dir):
                pkg = Package(name=name)
                installed_pkgs.append(pkg)
        solution = solve_from_sack(sack, world_deps, installed_pkgs,
                                    solver_flags)
        if isinstance(solution, tuple) and len(solution) == 4:
            to_install, to_remove, to_upgrade, errors = solution
    except Exception as e:
        log.debug(f"Sack solver unavailable: {e}")
        # fallback: use simple install/remove
        if packages:
            for p in packages:
                from .dpms_solver import Dependency as Dep
                to_install.append({"name": p})

    # filter locked packages
    for pkg in list(to_remove):
        if pkg.get("name") in locked:
            rprint(f"[yellow]Skipping locked:[/yellow] {pkg.get('name')}")
            to_remove.remove(pkg)

    for old, new in list(to_upgrade):
        if old.get("name") in locked:
            rprint(f"[yellow]Skipping locked:[/yellow] {old.get('name')}")
            to_upgrade.remove((old, new))

    summary = Summary(
        to_install=to_install,
        to_remove=to_remove,
        to_upgrade=to_upgrade,
    )
    return summary, errors, sack


# ── commit() — execute the changeset ────────────────────────────────

def commit(summary, policy):
    """Execute the changeset with progress display."""
    if policy.dry_run:
        rprint("[yellow]Dry run — nothing committed.[/yellow]")
        return True

    total = (len(summary.to_install) + len(summary.to_remove)
             + len(summary.to_upgrade))
    if total == 0:
        rprint("[green]Nothing to do.[/green]")
        return True

    stages = []
    if summary.to_remove:
        stages.append("Remove packages")
    if summary.to_upgrade:
        stages.append("Upgrade packages")
    if summary.to_install:
        stages.append("Install packages")

    sp = ProgressStages(stages, title="Commit", use_print=True)

    done = 0
    if summary.to_remove:
        sp.Busy("Removing packages")
        for pkg in summary.to_remove:
            name = pkg.get("name", "?")
            try:
                core.remove_package(name, verbose=False)
                done += 1
            except Exception as e:
                log.error(f"Failed to remove {name}: {e}")
                rprint(f"[red]Failed to remove {name}: {e}[/red]")
        sp.Done()

    if summary.to_upgrade:
        sp.Busy("Upgrading packages")
        for old, new in summary.to_upgrade:
            name = new.get("name", old.get("name", "?"))
            try:
                core.remove_package(name, verbose=False)
                core.install_package(name, verbose=False)
                done += 1
            except Exception as e:
                log.error(f"Failed to upgrade {name}: {e}")
                rprint(f"[red]Failed to upgrade {name}: {e}[/red]")
        sp.Done()

    if summary.to_install:
        sp.Busy("Installing packages")
        for pkg in summary.to_install:
            name = pkg.get("name", "?")
            try:
                core.install_package(name, verbose=False)
                done += 1
            except Exception as e:
                log.error(f"Failed to install {name}: {e}")
                rprint(f"[red]Failed to install {name}: {e}[/red]")
        sp.Done()

    rprint(f"[bold green]Done.[/bold green] {done}/{total} operations completed.")
    return done == total


# ── solve_and_commit() — main orchestrator ──────────────────────────

def solve_and_commit(policy=None, packages=None, command="install"):
    """Main solve-and-commit pipeline (like zypper's solve_and_commit)."""
    if policy is None:
        policy = CommitPolicy()

    need_another_run = True
    attempts = 0

    while need_another_run and attempts < 3:
        attempts += 1
        need_another_run = False

        rprint("[bold blue]Resolving dependencies...[/bold blue]")
        summary, errors, sack = resolve(policy, packages)

        if errors:
            rprint(f"\n[bold red]{len(errors)} dependency problem(s).[/bold red]")
            result = show_problems(errors, {}, sack)
            if result is None:
                rprint("[red]Cancelled.[/red]")
                return False
            if isinstance(result, CommitPolicy):
                policy = result
                need_another_run = True
                continue
            break

        summary.show()

        if not summary.has_changes:
            rprint("[green]Nothing to do.[/green]")
            return True

        if command == "install" and summary.to_remove:
            rprint("[yellow]Warning: install also triggers removals.[/yellow]")

        if not prompt_summary(summary, policy):
            return False

        return commit(summary, policy)

    if errors:
        rprint("[red]Could not resolve all dependencies.[/red]")
        return False
    return True


# ── list-updates (like zypper lu) ───────────────────────────────────

def list_updates():
    db_dir = core.DP_DB_DIR
    if not os.path.exists(db_dir):
        rprint("[yellow]No packages installed.[/yellow]")
        return

    installed = sorted(os.listdir(db_dir))
    if not installed:
        rprint("[yellow]No packages installed.[/yellow]")
        return

    locked = _load_locks()
    table = Table(title="Available Updates")
    table.add_column("Package", style="bold green")
    table.add_column("Installed")
    table.add_column("Available")
    table.add_column("Status")

    updates = 0
    for pkg in installed:
        found = core._find_package_in_repos(pkg, verbose=False)
        if not found:
            continue
        fn = os.path.basename(found)
        parsed = core._parse_package_archive_name(fn)
        if not parsed or not parsed[0]:
            continue
        _, avail_ver, _, _ = parsed
        avail_str = ".".join(str(v) for v in avail_ver) if avail_ver else "?"

        inst_ver = core._parse_installed_version(pkg)
        inst_str = ".".join(str(v) for v in inst_ver) if inst_ver else "?"

        status = "[red]locked[/red]" if pkg in locked else "[green]available[/green]"
        table.add_row(pkg, inst_str, avail_str, status)
        updates += 1

    if not updates:
        rprint("[green]All packages up to date.[/green]")
        return
    console.print(table)
    rprint(f"[dim]{updates} update(s) available.[/dim]")


# ── clean cache (like zypper clean) ─────────────────────────────────

def clean_cache():
    import shutil
    temp_dir = os.path.join(os.path.expanduser('~'), 'dpms_temp')
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
        rprint(f"[green]Cleaned[/green] {temp_dir}")
    cache_dir = core.REPO_CACHE_DIR
    if os.path.exists(cache_dir):
        for d in os.listdir(cache_dir):
            dp = os.path.join(cache_dir, d)
            if os.path.isdir(dp):
                shutil.rmtree(dp)
                rprint(f"[green]Removed cached repo:[/green] {d}")
    rprint("[bold green]Cache cleaned.[/bold green]")


# ── stats (like zypper products / zypper lu) ────────────────────────

def show_stats():
    db_dir = core.DP_DB_DIR
    if not os.path.exists(db_dir):
        rprint("[yellow]No packages installed.[/yellow]")
        return

    installed = sorted(os.listdir(db_dir))
    total_files = 0
    total_size = 0
    for pkg in installed:
        list_path = os.path.join(db_dir, pkg)
        try:
            with open(list_path) as f:
                files = [l.strip() for l in f if l.strip()]
                total_files += len(files)
                for fp in files:
                    if os.path.exists(fp):
                        total_size += os.path.getsize(fp)
        except Exception:
            pass

    table = Table(title="DPMS Stats")
    table.add_column("Metric", style="bold green")
    table.add_column("Value")
    table.add_row("Installed packages", str(len(installed)))
    table.add_row("Tracked files", str(total_files))
    table.add_row("Disk usage", f"{total_size / 1024**2:.1f} MB" if total_size else "?")
    table.add_row("Repositories", str(len(core.load_repo_list())))
    table.add_row("Architecture", core.DPMS_ARCH)
    console.print(table)
