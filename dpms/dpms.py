import argparse
import os
from pathlib import Path
import subprocess
import sys

from . import dpms_crash_handler
dpms_crash_handler.register_crash_handler()

from . import config
from . import dpms_core as core
from . import dpms_search as search_mod
from . import dpms_utils as utils
from . import dpms_logging
from . import dpms_history
from . import dpms_commit as commit_mod
from . import dpms_portcommit as portcommit_mod
from . import dpms_logs as logs_mod
from .dpms_commit import CommitPolicy
from .dpms_progress import ProgressStages
from .dpms_confirm import must_be_root, delete as confirm_delete
from .config import needs_privileges, reexec_with_privileges, PRIV_ESCALATOR, IS_ROOT
from rich import print as rprint

log = dpms_logging.setup_logger("dpms", logdir=os.path.expanduser("~/.cache/dpms/log"))


def _escalate_if_needed(op_name):
    if needs_privileges(op_name):
        if not PRIV_ESCALATOR:
            if must_be_root():
                return
            print(f"'{op_name}' needs root. Run with sudo or doas, "
                  f"or set DPMS_ROOT to a user-writable path.")
            sys.exit(1)
        rprint(f"[yellow]'{op_name}' needs root — re-executing with:[/yellow]")
        rprint(f"  [bold]{PRIV_ESCALATOR} {' '.join(sys.argv)}[/bold]")
        sys.stdout.flush()
        sys.stderr.flush()
        reexec_with_privileges()
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        description="DPMS - Discovery Package Manager (cross-platform)",
        allow_abbrev=False,
    )

    parser.add_argument("--global", "-g", dest="global_dir", metavar="DIR",
                        help="Install to a global directory (e.g. /usr/local)")
    parser.add_argument("--install", "-i", nargs="+", metavar="PKG", help="Install one or more packages")
    parser.add_argument("--uninstall", "-r", metavar="PKG", help="Uninstall a package (remove)")
    parser.add_argument("--list", "--installed", "-l", "-inpc", action="store_true", help="List installed packages")
    parser.add_argument("--installable", "-a", action="store_true", help="Show all installable packages")
    parser.add_argument("--reset", action="store_true", help="Reset DPMS configuration")
    parser.add_argument("--gui", action="store_true", help="Launch DPMS GUI")
    parser.add_argument("--tui", "-T", action="store_true", help="Launch DPMS Textual TUI")
    parser.add_argument("--tar", metavar="FOLDER", help="Create tar.xz from a folder")
    parser.add_argument("--maketar", nargs="+", metavar="FOLDER [NAME VERSION [ARCH]]", help="Create .dp.tar.xz package. Use --rc for RC suffix.")
    parser.add_argument("--rc", metavar="N", help="Release candidate number (e.g. 1) for --maketar")
    parser.add_argument("--get", nargs="*", metavar="ARG", help="Run DPMS-GET, optionally with subcommand args")

    parser.add_argument("--search", "-s", metavar="PKG", nargs="?", const=True, help="Search for a package (with animation)")
    parser.add_argument("--add-repo", nargs='+', metavar="NAME URL [ARCH]", help="Add a new repository (NAME, URL, optional ARCH)")
    parser.add_argument("--remove-repo", metavar="NAME", help="Remove a repository")
    parser.add_argument("--toggle-repo", metavar="NAME", help="Enable/disable a repository")
    parser.add_argument("--repo-list", nargs="?", const=True, metavar="NAME", help="List repos or show a specific repo's details")
    parser.add_argument("--list-repo", nargs="?", const=True, metavar="NAME", help="Show repository details (alias for --repo-list)")
    parser.add_argument("--sync", "-S", action="store_true", help="Check connectivity to all repositories")
    parser.add_argument("--update", "-U", action="store_true", help="Update package metadata from all repositories")
    parser.add_argument("--upgrade", "-u", action="store_true", help="Upgrade all installed packages to latest versions")
    parser.add_argument("--download", metavar="PKG", help="Download a package archive without installing")
    parser.add_argument("--reinstall", metavar="PKG", help="Reinstall a package")
    parser.add_argument("--clean", "--autoremove", action="store_true", help="Remove orphaned packages")
    parser.add_argument("--depends", metavar="PKG", help="Show dependency tree for a package")
    parser.add_argument("--rdepends", metavar="PKG", help="Show reverse dependencies for a package")
    parser.add_argument("--what-owns", metavar="FILE", help="Find which package owns a file")
    parser.add_argument("--check", action="store_true", help="Check package integrity and missing files")
    parser.add_argument("--info", "-I", metavar="PKG", help="Show detailed package info")
    parser.add_argument("--files", "-f", metavar="PKG", help="List files installed by a package")
    parser.add_argument("--verify", "-V", metavar="PKG", help="Verify installed package files exist")
    parser.add_argument("--rescue", "-R", action="store_true", help="Rescue mode - repair DPMS installation")
    parser.add_argument("--history", action="store_true", help="Show transaction history")
    parser.add_argument("--history-last", type=int, metavar="N", help="Show last N transactions")
    parser.add_argument("--arch", action="store_true", help="Show system architecture")
    # zypper-style features
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without committing")
    parser.add_argument("--downgrade", "--oldpackage", nargs="?", const="__flag__", metavar="PKG", help="Downgrade a package, or use with --install to allow downgrading")

    parser.add_argument("--force-resolution", action="store_true", help="Force dependency resolution")
    parser.add_argument("--no-recommends", action="store_true", help="Only required dependencies (no recommends)")
    parser.add_argument("--clean-deps", action="store_true", help="Remove orphaned dependencies on remove")
    parser.add_argument("--lock", metavar="PKG", help="Lock a package to prevent changes")
    parser.add_argument("--unlock", metavar="PKG", help="Unlock a package")
    parser.add_argument("--locked-list", action="store_true", help="Show locked packages")
    parser.add_argument("--repo-priority", nargs=2, metavar=("NAME", "PRIO"), help="Set repository priority")
    parser.add_argument("--list-updates", action="store_true", help="Show available package updates")
    parser.add_argument("--clean-cache", action="store_true", help="Clean cached packages and repo data")
    parser.add_argument("--stats", action="store_true", help="Show package statistics")
    parser.add_argument("--feedback", action="store_true", help="Send feedback to the DPMS team")
    parser.add_argument("--export-installed", metavar="FILE", help="Export installed package list to file")
    parser.add_argument("--import-installed", metavar="FILE", help="Install packages from exported list")
    parser.add_argument("--verify-all", action="store_true", help="Verify all installed packages")
    parser.add_argument("--why", metavar="PKG", help="Show why a package is installed")
    parser.add_argument("--hold", metavar="PKG", help="Hold a package to prevent upgrades")
    parser.add_argument("--unhold", metavar="PKG", help="Release a held package")
    parser.add_argument("--list-held", action="store_true", help="Show held packages")
    parser.add_argument("--duplicates", action="store_true", help="Find duplicate files across packages")
    parser.add_argument("--backup", metavar="DIR", help="Back up package database")
    parser.add_argument("--restore", metavar="FILE", help="Restore package database from backup")
    parser.add_argument("--compare", nargs=2, metavar=("V1", "V2"), help="Compare two version strings")
    parser.add_argument("--changelog", metavar="PKG", help="Show changelog for a package")
    parser.add_argument("--port-commit", action="store_true", help="Commit changes to local ports")
    parser.add_argument("--dlr-verify", action="store_true", help="Verify SHA hashes in dlr.log")
    parser.add_argument("--list-nft", action="store_true", help="List directories excluded with nft.log")
    parser.add_argument("--purge", metavar="PKG", help="Remove package including config and data files")
    parser.add_argument("--size", metavar="PKG", help="Show installed size of a package")
    parser.add_argument("--list-type", nargs=2, metavar=("PKG", "EXT"), help="List files by extension in a package")
    parser.add_argument("--recent", nargs="?", const=10, type=int, metavar="N", help="Show recently installed packages")

    # apt-ftparchive-style commands
    parser.add_argument("--gen-packages", metavar="DIR", help="Generate Packages index from a directory of archives")
    parser.add_argument("--gen-sources", metavar="DIR", help="Generate Sources index from a directory of archives")
    parser.add_argument("--gen-contents", metavar="DIR", help="Generate Contents file from a directory of archives")
    parser.add_argument("--gen-release", metavar="DIR", help="Generate Release file with checksums for a repository directory")
    parser.add_argument("--gen-repo", metavar="DIR", help="Generate full repository metadata (Packages + Sources + Contents + Release)")
    parser.add_argument("--gen-generate", metavar="CONFIG", help="Generate repository from a config file (apt-ftparchive generate style)")
    parser.add_argument("--gen-clean", metavar="DIR", help="Clean cache files from a repository directory")
    parser.add_argument("--version", action="store_true", help="Show version")

    args, remaining = parser.parse_known_args()

    if args.global_dir:
        d = os.path.abspath(os.path.expanduser(args.global_dir))
        os.environ['DPMS_ROOT'] = d
        config.INSTALL_ROOT_DIR = d
        config.DP_DB_DIR = os.path.join(d, 'var', 'lib', 'dp', 'installed')
        core.INSTALL_ROOT_DIR = d
        core.DP_DB_DIR = os.path.join(d, 'var', 'lib', 'dp', 'installed')

    if args.version:
        from . import __version__
        rprint(f"[bold cyan]DPMS version {__version__}[/bold cyan]")
        sys.exit(0)

    # warn about unknown flags instead of silently ignoring them
    unknown = [a for a in remaining if a.startswith('-')]
    if unknown and args.get is None:
        rprint(f"[red]Unknown flag(s):[/red] {' '.join(unknown)}")
        rprint(f"[yellow]Use [bold]--help[/bold] to see available options.[/yellow]")
        sys.exit(1)

    if args.get is not None:
        get_argv = [sys.executable, "-m", "dpms.dpms_get"]
        if args.get:
            get_argv.extend(args.get)
        if remaining:
            get_argv.extend(remaining)
        try:
            subprocess.run(get_argv, check=True)
        except subprocess.CalledProcessError as e:
            rprint(f"[red]dpms-get failed with exit code {e.returncode}[/red]")
            sys.exit(e.returncode)
    elif args.search:
        if args.search is True:
            search_mod.interative_search()
        else:
            search_mod.search_animation(args.search)
    elif args.install or args.uninstall:
        downgrade_flag = bool(args.downgrade)
        has_policy = args.dry_run or downgrade_flag or args.force_resolution or args.no_recommends
        if has_policy:
            policy = CommitPolicy(
                dry_run=args.dry_run or False,
                force_resolution=args.force_resolution or False,
                no_recommends=args.no_recommends or False,
                allow_downgrade=downgrade_flag,
            )
            if args.install:
                if not policy.dry_run:
                    _escalate_if_needed('install')
                commit_mod.solve_and_commit(policy, args.install)
            else:
                if not policy.dry_run:
                    _escalate_if_needed('uninstall')
                commit_mod.solve_and_commit(policy, [args.uninstall], command="remove")
        elif args.install:
            _escalate_if_needed('install')
            sp = ProgressStages(use_print=True)
            for pkg in args.install:
                sp.Busy(f"Installing {pkg}")
                core.install_package(pkg)
                sp.Done()
        elif args.uninstall:
            if not confirm_delete(args.uninstall):
                sys.exit(0)
            _escalate_if_needed('uninstall')
            sp = ProgressStages(use_print=True)
            sp.Busy(f"Removing {args.uninstall}")
            core.remove_package(args.uninstall)
            sp.Done()
    elif args.downgrade and args.downgrade != "__flag__":
        if not args.dry_run:
            _escalate_if_needed('install')
        sp = ProgressStages(use_print=True)
        sp.Busy(f"Downgrading {args.downgrade}")
        core.downgrade_package(args.downgrade, dry_run=args.dry_run)
        sp.Done()
    elif args.downgrade == "__flag__":
        rprint("[yellow]Usage: --downgrade PKGNAME  (or --downgrade with --install to allow downgrades)[/yellow]")
    elif args.list:
        core.list_installed()
    elif args.installable:
        core.show_installable()
    elif args.add_repo:
        _escalate_if_needed('install')
        if len(args.add_repo) == 3:
            core.add_repo(args.add_repo[0], args.add_repo[1], arch=args.add_repo[2])
        elif len(args.add_repo) == 2:
            core.add_repo(args.add_repo[0], args.add_repo[1])
        else:
            rprint("[red]Usage: --add-repo NAME URL [ARCH][/red]")
    elif args.remove_repo:
        if not confirm_delete(f"repository '{args.remove_repo}'"):
            sys.exit(0)
        _escalate_if_needed('install')
        core.remove_repo(args.remove_repo)
    elif args.toggle_repo:
        core.toggle_repo(args.toggle_repo)
    elif args.repo_list is not None or args.list_repo is not None:
        name = args.repo_list if args.repo_list is not None else args.list_repo
        if name is True:
            core.list_repos()
        else:
            core.list_repos(name)
    elif args.sync:
        _escalate_if_needed('sync')
        core.sync_repos()
    elif args.update:
        _escalate_if_needed('sync')
        sp = ProgressStages(use_print=True)
        sp.Busy("Updating repositories")
        core.update_repos()
        sp.Done()
    elif args.upgrade:
        has_policy = args.dry_run or args.downgrade or args.force_resolution or args.no_recommends
        if has_policy:
            policy = CommitPolicy(
                dry_run=args.dry_run or False,
                force_resolution=args.force_resolution or False,
                no_recommends=args.no_recommends or False,
                allow_downgrade=bool(args.downgrade),
            )
            if not policy.dry_run:
                _escalate_if_needed('install')
            db_dir = os.path.expanduser(core.DP_DB_DIR)
            upgrade_pkgs = sorted(os.listdir(db_dir)) if os.path.isdir(db_dir) else []
            commit_mod.solve_and_commit(policy, upgrade_pkgs, command="upgrade")
        else:
            _escalate_if_needed('install')
            sp = ProgressStages(use_print=True)
            sp.Busy("Upgrading all packages")
            core.upgrade_packages()
            sp.Done()
    elif args.download:
        _escalate_if_needed('install')
        core.download_package(args.download)
    elif args.reinstall:
        _escalate_if_needed('install')
        core.reinstall_package(args.reinstall)
    elif args.clean_deps or args.clean:
        _escalate_if_needed('uninstall')
        core.clean_orphaned()
    elif args.depends:
        core.show_depends(args.depends)
    elif args.rdepends:
        core.show_rdepends(args.rdepends)
    elif args.what_owns:
        core.what_owns(args.what_owns)
    elif args.check:
        core.check_integrity()
    elif args.info:
        core.package_info(args.info)
    elif args.files:
        core.list_package_files(args.files)
    elif args.verify:
        core.verify_package(args.verify)
    elif args.history:
        dpms_history.show_history()
    elif args.history_last:
        dpms_history.show_history(limit=args.history_last)
    elif args.arch:
        from rich.table import Table
        from rich.console import Console
        from .config import DPMS_ARCH, MACHINE
        arch_con = Console()
        arch_table = Table(title="System Architecture")
        arch_table.add_column("Field", style="bold green")
        arch_table.add_column("Value")
        arch_table.add_row("Detected arch", DPMS_ARCH)
        arch_table.add_row("Raw machine", MACHINE)
        arch_con.print(arch_table)
    elif args.rescue:
        core.rescue_mode()
    elif args.reset:
        _escalate_if_needed('reset')
        utils.reset_config()
    elif args.tui:
        from .dpms_tui import main as tui_main
        tui_main()
    elif args.gui:
        utils.launch_gui()
    elif args.lock:
        commit_mod.lock_package(args.lock)
    elif args.unlock:
        commit_mod.unlock_package(args.unlock)
    elif args.locked_list:
        commit_mod.list_locked()
    elif args.repo_priority:
        commit_mod.set_repo_priority(args.repo_priority[0], int(args.repo_priority[1]))
    elif args.list_updates:
        commit_mod.list_updates()
    elif args.clean_cache:
        commit_mod.clean_cache()
    elif args.export_installed:
        core.export_installed(args.export_installed)
    elif args.import_installed:
        core.import_installed(args.import_installed)
    elif args.verify_all:
        core.verify_all()
    elif args.why:
        core.show_why(args.why)
    elif args.hold:
        core.hold_package(args.hold)
    elif args.unhold:
        core.unhold_package(args.unhold)
    elif args.list_held:
        core.list_held()
    elif args.duplicates:
        core.find_duplicates()
    elif args.backup:
        core.backup_db(args.backup)
    elif args.restore:
        core.restore_db(args.restore)
    elif args.compare:
        core.compare_versions(args.compare[0], args.compare[1])
    elif args.changelog:
        core.show_changelog(args.changelog)
    elif args.gen_packages:
        from .dpms_ftparchive import gen_packages
        gen_packages(args.gen_packages)
    elif args.gen_sources:
        from .dpms_ftparchive import gen_sources
        gen_sources(args.gen_sources)
    elif args.gen_contents:
        from .dpms_ftparchive import gen_contents
        pkgs = core.load_repo_list().get('packages', [])
        gen_contents(args.gen_contents, pkgs)
    elif args.gen_release:
        from .dpms_ftparchive import gen_release
        gen_release(args.gen_release)
    elif args.gen_repo:
        from .dpms_ftparchive import gen_repo
        gen_repo(args.gen_repo)
    elif args.gen_generate:
        from .dpms_ftparchive import gen_generate
        gen_generate(args.gen_generate)
    elif args.gen_clean:
        from .dpms_ftparchive import gen_clean
        gen_clean(args.gen_clean)
    elif args.stats:
        commit_mod.show_stats()
    elif args.feedback:
        from .dpms_feedback import send_feedback
        send_feedback()
    elif args.dlr_verify:
        if not logs_mod.cmd_dlr_verify():
            sys.exit(1)
    elif args.list_nft:
        if not logs_mod.cmd_list_nft():
            sys.exit(1)
    elif args.purge:
        _escalate_if_needed('uninstall')
        core.purge_package(args.purge)
    elif args.size:
        core.show_package_size(args.size)
    elif args.list_type:
        core.list_files_by_type(args.list_type[0], args.list_type[1])
    elif args.recent is not None:
        core.list_recent(n=args.recent)
    elif args.port_commit:
        if not portcommit_mod.port_commit():
            sys.exit(1)
    elif args.tar:
        core.make_dp_archive(Path(args.tar).expanduser().resolve())
    elif args.maketar:
        folder = Path(args.maketar[0]).expanduser().resolve()
        name = args.maketar[1] if len(args.maketar) > 1 else None
        version = args.maketar[2] if len(args.maketar) > 2 else None
        arch = args.maketar[3] if len(args.maketar) > 3 else None
        core.make_dp_archive(str(folder), name=name, version=version, arch=arch, rc=args.rc)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
