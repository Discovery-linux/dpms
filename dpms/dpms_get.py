import sys
import os
import argparse
from rich.console import Console
from rich import print as rprint

console = Console()
DPMS_GET_VERSION = "1.0.0"

try:
    from .dpms_core import (
        install_package, remove_package, search_package, rescue_mode,
        upgrade_packages, download_package, reinstall_package,
        clean_orphaned, show_depends, show_rdepends, what_owns,
        check_integrity, show_changelog, DPMSCoreError,
        NetworkError, ArchiveError, InvalidSourceError,
    )
    from .dpms_tags import show_version, show_package_info
    from .dpms_utils import main as dpms_utils_main
    from . import dpms_core as core
    from .dpms_commit import clean_cache, list_updates, show_stats
    from .dpms_portcommit import port_commit
    from .dpms_logs import cmd_dlr_verify, cmd_list_nft
except ImportError:
    from dpms_core import (
        install_package, remove_package, search_package, rescue_mode,
        upgrade_packages, download_package, reinstall_package,
        clean_orphaned, show_depends, show_rdepends, what_owns,
        check_integrity, show_changelog, DPMSCoreError,
        NetworkError, ArchiveError, InvalidSourceError,
    )
    from dpms_tags import show_version, show_package_info
    from dpms_utils import main as dpms_utils_main
    import dpms_core as core
    from dpms_commit import clean_cache, list_updates, show_stats
    from dpms_portcommit import port_commit
    from dpms_logs import cmd_dlr_verify, cmd_list_nft


def cmd_update(args):
    from .dpms_core import update_repos
    update_repos()


def cmd_upgrade(args):
    upgrade_packages(verbose=getattr(args, 'verbose', False))


def cmd_dist_upgrade(args):
    rprint("[bold]Performing distribution upgrade...[/bold]")
    upgrade_packages(verbose=getattr(args, 'verbose', False))


def cmd_install(args):
    for pkg in args.package:
        install_package(pkg, verbose=getattr(args, 'verbose', False))


def cmd_reinstall(args):
    for pkg in args.package:
        reinstall_package(pkg, verbose=getattr(args, 'verbose', False))


def cmd_remove(args):
    for pkg in args.package:
        remove_package(pkg, verbose=getattr(args, 'verbose', False))


def cmd_purge(args):
    for pkg in args.package:
        remove_package(pkg, verbose=getattr(args, 'verbose', False))


def cmd_autoremove(args):
    rprint("[bold]Removing orphaned packages...[/bold]")
    clean_orphaned(verbose=getattr(args, 'verbose', False))


def cmd_markauto(args):
    for pkg in args.packages:
        rprint(f"[green]{pkg} set to automatically installed.[/green]")
    rprint("[yellow]Note: use 'dpms-mark auto' for full support.[/yellow]")


def cmd_unmarkauto(args):
    for pkg in args.packages:
        rprint(f"[green]{pkg} set to manually installed.[/green]")
    rprint("[yellow]Note: use 'dpms-mark manual' for full support.[/yellow]")


def cmd_search(args):
    search_package(args.query, verbose=getattr(args, 'verbose', False))


def cmd_info(args):
    show_package_info(args.package, verbose=getattr(args, 'verbose', False))


def cmd_rescue(args):
    rescue_mode()


def cmd_download(args):
    download_package(args.package, verbose=getattr(args, 'verbose', False))


def cmd_clean(args):
    rprint("[bold]Cleaning package cache...[/bold]")
    clean_cache()


def cmd_autoclean(args):
    rprint("[bold]Cleaning old cached packages...[/bold]")
    clean_cache()


def cmd_distclean(args):
    rprint("[bold]Cleaning all caches...[/bold]")
    clean_cache()
    temp_dir = os.path.join(os.path.expanduser('~'), 'dpms_temp')
    if os.path.exists(temp_dir):
        import shutil
        shutil.rmtree(temp_dir)
        rprint(f"[green]Cleaned[/green] {temp_dir}")


def cmd_check(args):
    check_integrity(verbose=getattr(args, 'verbose', False))


def cmd_depends(args):
    show_depends(args.package, verbose=getattr(args, 'verbose', False))


def cmd_rdepends(args):
    show_rdepends(args.package, verbose=getattr(args, 'verbose', False))


def cmd_what_owns(args):
    what_owns(args.path, verbose=getattr(args, 'verbose', False))


def cmd_source(args):
    rprint(f"[yellow]Source download for '{args.package}' not yet implemented in dpms-get.[/yellow]")
    rprint("[dim]Try: dpms --get download <pkg>[/dim]")


def cmd_build_dep(args):
    rprint(f"[yellow]Build-dep for '{args.package}' not yet implemented.[/yellow]")
    rprint("[dim]Install build dependencies manually with dpms --install[/dim]")


def cmd_satisfy(args):
    rprint(f"[yellow]Satisfy '{args.target}' not yet implemented.[/yellow]")


def cmd_changelog(args):
    show_changelog(args.package)


def cmd_list_updates(args):
    list_updates()


def cmd_stats(args):
    show_stats()


def cmd_port_commit(args):
    from .dpms_portcommit import port_commit
    if not port_commit():
        sys.exit(1)


def cmd_dlr_verify_handler(args):
    from .dpms_logs import cmd_dlr_verify
    if not cmd_dlr_verify():
        sys.exit(1)


def cmd_list_nft_handler(args):
    from .dpms_logs import cmd_list_nft
    if not cmd_list_nft():
        sys.exit(1)


def main():
    console.print("[bold green]Welcome to DPMS-GET[/bold green]")
    console.print("Type [bold yellow]--help[/bold yellow] for usage.\n")

    parser = argparse.ArgumentParser(
        description='DPMS-GET — dpms-get command-line interface',
    )
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output')
    parser.add_argument('-V', '--version', action='store_true',
                        help='Show version')
    parser.add_argument('--exit', action='store_true',
                        help='Return to DPMS main terminal')

    sub = parser.add_subparsers(dest='command', help='Commands')

    p = sub.add_parser('update', help='Resynchronize package metadata')
    p = sub.add_parser('upgrade', help='Upgrade all installed packages')
    p = sub.add_parser('dist-upgrade', help='Distribution upgrade')
    sub.add_parser('full-upgrade', add_help=False)

    p = sub.add_parser('install', help='Install package(s)')
    p.add_argument('package', nargs='+', help='Package name(s)')

    p = sub.add_parser('reinstall', help='Reinstall package(s)')
    p.add_argument('package', nargs='+', help='Package name(s)')

    p = sub.add_parser('remove', help='Remove package(s)')
    p.add_argument('package', nargs='+', help='Package name(s)')

    p = sub.add_parser('purge', help='Remove package(s) and config files')
    p.add_argument('package', nargs='+', help='Package name(s)')

    sub.add_parser('autoremove', help='Remove automatically unused packages')
    sub.add_parser('auto-remove', add_help=False)
    sub.add_parser('autopurge', add_help=False)

    p = sub.add_parser('markauto', help='Mark packages as automatically installed')
    p.add_argument('packages', nargs='+', help='Package name(s)')

    p = sub.add_parser('unmarkauto', help='Mark packages as manually installed')
    p.add_argument('packages', nargs='+', help='Package name(s)')

    p = sub.add_parser('search', help='Search for packages')
    p.add_argument('query', help='Search term')

    p = sub.add_parser('info', help='Show package information')
    p.add_argument('package', help='Package name')

    sub.add_parser('rescue', help='Rescue/repair DPMS installation')

    p = sub.add_parser('download', help='Download binary package')
    p.add_argument('package', help='Package name or URL')

    sub.add_parser('clean', help='Erase downloaded archive files')
    sub.add_parser('autoclean', help='Erase old downloaded archive files')
    sub.add_parser('auto-clean', add_help=False)
    sub.add_parser('distclean', help='Erase all caches')
    sub.add_parser('dist-clean', add_help=False)

    sub.add_parser('check', help='Verify package integrity')

    p = sub.add_parser('depends', help='Show dependency tree')
    p.add_argument('package', help='Package name')

    p = sub.add_parser('rdepends', help='Show reverse dependencies')
    p.add_argument('package', help='Package name')

    p = sub.add_parser('what-owns', help='Find which package owns a file')
    p.add_argument('path', help='Path to the file')

    p = sub.add_parser('source', help='Download source archive')
    p.add_argument('package', help='Source package name')

    p = sub.add_parser('build-dep', help='Install build dependencies')
    p.add_argument('package', help='Source package name')

    p = sub.add_parser('satisfy', help='Satisfy dependency strings')
    p.add_argument('target', help='Dependency string')

    p = sub.add_parser('changelog', help='Show changelog for a package')
    p.add_argument('package', help='Package name')

    sub.add_parser('list-updates', help='Show available updates')
    sub.add_parser('stats', help='Show package statistics')
    sub.add_parser('port-commit', help='Commit changes to local ports')
    sub.add_parser('dlr-verify', help='Verify SHA hashes in dlr.log')
    sub.add_parser('list-nft', help='List directories excluded with nft.log')

    args, unknown = parser.parse_known_args()

    if args.version:
        show_version("DPMS-GET")
        sys.exit(0)

    if args.exit:
        dpms_utils_main()
        return

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    cmds = {
        'update': cmd_update,
        'upgrade': cmd_upgrade,
        'dist-upgrade': cmd_dist_upgrade,
        'full-upgrade': cmd_dist_upgrade,
        'install': cmd_install,
        'reinstall': cmd_reinstall,
        'remove': cmd_remove,
        'purge': cmd_purge,
        'autoremove': cmd_autoremove,
        'auto-remove': cmd_autoremove,
        'autopurge': cmd_autoremove,
        'markauto': cmd_markauto,
        'unmarkauto': cmd_unmarkauto,
        'search': cmd_search,
        'info': cmd_info,
        'rescue': cmd_rescue,
        'download': cmd_download,
        'clean': cmd_clean,
        'autoclean': cmd_autoclean,
        'auto-clean': cmd_autoclean,
        'distclean': cmd_distclean,
        'dist-clean': cmd_distclean,
        'check': cmd_check,
        'depends': cmd_depends,
        'rdepends': cmd_rdepends,
        'what-owns': cmd_what_owns,
        'source': cmd_source,
        'build-dep': cmd_build_dep,
        'satisfy': cmd_satisfy,
        'changelog': cmd_changelog,
        'list-updates': cmd_list_updates,
        'stats': cmd_stats,
        'port-commit': cmd_port_commit,
        'dlr-verify': cmd_dlr_verify_handler,
        'list-nft': cmd_list_nft_handler,
    }

    handler = cmds.get(args.command)
    if handler:
        try:
            handler(args)
        except (DPMSCoreError, NetworkError, ArchiveError,
                InvalidSourceError) as e:
            console.print(f"[bold red]Error:[/bold red] {e}")
        except Exception as e:
            console.print(f"[bold red]Unexpected error:[/bold red] {e}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
