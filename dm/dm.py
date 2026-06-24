import argparse
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile

from rich.console import Console
from rich.table import Table
from rich import print as rprint
from rich import box

try:
    from importlib.metadata import version as _get_ver
except ImportError:
    from importlib_metadata import version as _get_ver

PKG = "dpms"
PIN_FILE = os.path.join(os.path.expanduser('~/.config/dm'), '.version_pins.json')

console = Console()


def _check(pkg):
    if pkg != PKG:
        rprint(f"[red]dm only manages '{PKG}', not '{pkg}'.[/red]")
        sys.exit(1)


def _installed(pkg):
    try:
        return _get_ver(pkg)
    except Exception:
        return None


def _versions(pkg):
    try:
        r = subprocess.run([sys.executable, '-m', 'pip', 'index', 'versions', pkg],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return None
        m = re.search(r'Available versions:\s*(.+)', r.stdout)
        return [v.strip() for v in m.group(1).split(',')] if m else None
    except Exception:
        return None


def _pip_install(spec):
    return subprocess.run([sys.executable, '-m', 'pip', 'install', spec],
                          capture_output=True, text=True)


def _pip_download(spec, dest):
    return subprocess.run([sys.executable, '-m', 'pip', 'download', '--no-deps', '--dest', dest, spec],
                          capture_output=True, text=True)


def _load_pins():
    if not os.path.exists(PIN_FILE):
        return {}
    try:
        with open(PIN_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_pins(pins):
    os.makedirs(os.path.dirname(PIN_FILE), exist_ok=True)
    with open(PIN_FILE, 'w') as f:
        json.dump(pins, f, indent=2)


def cmd_list(args):
    _check(args.package)
    rprint(f"[bold]Available versions of [cyan]{args.package}[/cyan] from PyPI:[/bold]\n")
    versions = _versions(args.package)
    if not versions:
        rprint(f"[yellow]Could not fetch versions for '{args.package}'.[/yellow]")
        return
    installed = _installed(args.package)
    table = Table(title=f"{args.package} ({len(versions)})", box=box.ROUNDED)
    table.add_column("Version", style="bold cyan")
    for ver in versions:
        m = " [bold green]\u2190 installed[/bold green]" if ver == installed else ""
        table.add_row(f"{ver}{m}")
    console.print(table)


def cmd_current(args):
    if args.package:
        _check(args.package)
        ver = _installed(args.package)
        if not ver:
            rprint(f"[yellow]'{args.package}' is not installed.[/yellow]")
            return
        pins = _load_pins()
        table = Table(title=f"{args.package}", box=box.ROUNDED)
        table.add_column("Field", style="bold green")
        table.add_column("Value")
        table.add_row("Version", ver)
        if args.package in pins:
            table.add_row("Pinned", pins[args.package])
        console.print(table)
    else:
        ver = _installed(PKG)
        if not ver:
            rprint(f"[yellow]'{PKG}' is not installed.[/yellow]")
            return
        pins = _load_pins()
        pinned = pins.get(PKG, "")
        table = Table(title=f"{PKG}", box=box.ROUNDED)
        table.add_column("Field", style="bold green")
        table.add_column("Value")
        table.add_row("Version", ver)
        if pinned:
            table.add_row("Pinned", pinned)
        console.print(table)


def cmd_use(args):
    _check(args.package)
    pins = _load_pins()
    if args.package in pins:
        rprint(f"[red]'{args.package}' is pinned to {pins[args.package]}. Unpin first.[/red]")
        return
    cur = _installed(args.package)
    if cur == args.version:
        rprint(f"[yellow]Already on {args.version}.[/yellow]")
        return
    spec = f"{args.package}=={args.version}"
    rprint(f"[bold]{args.package}: [yellow]{cur or 'not installed'}[/yellow] \u2192 [green]{args.version}[/green][/bold]")
    r = _pip_install(spec)
    if r.returncode != 0:
        rprint(f"[red]Failed:[/red]\n{r.stderr}")
        sys.exit(1)
    rprint(f"[bold green]Done.[/bold green] {args.package} now at {args.version}")


def cmd_compare(args):
    if args.v1 == args.v2:
        rprint(f"[yellow]{args.v1} == {args.v2}[/yellow]")
    elif args.v1 < args.v2:
        rprint(f"[green]{args.v1} < {args.v2}[/green]")
    else:
        rprint(f"[green]{args.v1} > {args.v2}[/green]")


def cmd_diff(args):
    _check(args.package)
    v1, v2 = args.v1, args.v2
    with tempfile.TemporaryDirectory(prefix='dm-diff-') as tmp:
        d1, d2 = os.path.join(tmp, 'a'), os.path.join(tmp, 'b')
        os.makedirs(d1), os.makedirs(d2)

        r1 = _pip_download(f"{args.package}=={v1}", d1)
        if r1.returncode != 0:
            rprint(f"[red]Could not download {args.package}=={v1}[/red]"); return
        r2 = _pip_download(f"{args.package}=={v2}", d2)
        if r2.returncode != 0:
            rprint(f"[red]Could not download {args.package}=={v2}[/red]"); return

        def _list(path):
            s = set()
            for f in os.listdir(path):
                fp = os.path.join(path, f)
                if f.endswith(('.tar.gz', '.tar.xz', '.tar.bz2', '.whl')):
                    try:
                        with tarfile.open(fp, 'r:*') as t:
                            for m in t.getmembers():
                                s.add(m.name)
                    except Exception:
                        s.add(f)
                else:
                    s.add(f)
            return s

        a1, a2 = _list(d1), _list(d2)
        added, removed = sorted(a2 - a1), sorted(a1 - a2)
        if not added and not removed:
            rprint(f"[yellow]No differences between {v1} and {v2}.[/yellow]"); return
        table = Table(title=f"Diff {args.package} {v1} \u2194 {v2}", box=box.ROUNDED)
        table.add_column("", style="bold")
        table.add_column("File")
        for f in added:
            table.add_row("[green]+[/green]", f)
        for f in removed:
            table.add_row("[red]-[/red]", f)
        table.add_row("", f"[dim]{len(added)} added, {len(removed)} removed[/dim]")
        console.print(table)


def cmd_history(args):
    rprint("[yellow]History unavailable in pip-backed mode.[/yellow]")


def cmd_pin(args):
    _check(args.package)
    ver = _installed(args.package)
    if not ver:
        rprint(f"[yellow]'{args.package}' not installed.[/yellow]"); return
    pins = _load_pins()
    pins[args.package] = ver
    _save_pins(pins)
    rprint(f"[green]Pinned[/green] {args.package} at [cyan]{ver}[/cyan]")


def cmd_unpin(args):
    _check(args.package)
    pins = _load_pins()
    if args.package not in pins:
        rprint(f"[yellow]'{args.package}' not pinned.[/yellow]"); return
    del pins[args.package]
    _save_pins(pins)
    rprint(f"[green]Unpinned[/green] {args.package}")


def cmd_list_pinned(args):
    pins = _load_pins()
    if not pins:
        rprint("[yellow]Nothing pinned.[/yellow]"); return
    table = Table(title="Pinned", box=box.ROUNDED)
    table.add_column("Package", style="bold green")
    table.add_column("Version", style="cyan")
    for pkg, ver in sorted(pins.items()):
        table.add_row(pkg, ver)
    console.print(table)


def cmd_rollback(args):
    _check(args.package)
    cur = _installed(args.package)
    if not cur:
        rprint(f"[yellow]'{args.package}' not installed.[/yellow]"); return
    pins = _load_pins()
    if args.package in pins:
        rprint(f"[red]'{args.package}' is pinned. Unpin first.[/red]"); return
    versions = _versions(args.package)
    if not versions:
        rprint(f"[red]Could not fetch versions.[/red]"); return
    try:
        idx = versions.index(cur)
    except ValueError:
        rprint(f"[yellow]Current version '{cur}' not in PyPI listing.[/yellow]"); return
    if idx + 1 >= len(versions):
        rprint(f"[yellow]No older version (current: {cur}.[/yellow]"); return
    prev = versions[idx + 1]
    rprint(f"[bold]Rollback: [yellow]{cur}[/yellow] \u2192 [green]{prev}[/green][/bold]")
    r = _pip_install(f"{args.package}=={prev}")
    if r.returncode != 0:
        rprint(f"[red]Rollback failed:[/red]\n{r.stderr}"); sys.exit(1)
    rprint(f"[bold green]Done.[/bold green] {args.package} now at {prev}")


def main():
    parser = argparse.ArgumentParser(description="dm - DPMS Version Manager", allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser("list"); p.add_argument("package")
    p = sub.add_parser("current"); p.add_argument("package", nargs="?")
    p = sub.add_parser("use"); p.add_argument("package"); p.add_argument("version")
    p = sub.add_parser("compare"); p.add_argument("v1"); p.add_argument("v2")
    p = sub.add_parser("diff"); p.add_argument("package"); p.add_argument("v1"); p.add_argument("v2")
    p = sub.add_parser("history"); p.add_argument("package", nargs="?")
    p = sub.add_parser("pin"); p.add_argument("package")
    p = sub.add_parser("unpin"); p.add_argument("package")
    sub.add_parser("list-pinned")
    p = sub.add_parser("rollback"); p.add_argument("package")

    args = parser.parse_args()
    if not args.command:
        parser.print_help(); return

    {
        "list": cmd_list, "current": cmd_current, "use": cmd_use,
        "compare": cmd_compare, "diff": cmd_diff, "history": cmd_history,
        "pin": cmd_pin, "unpin": cmd_unpin, "list-pinned": cmd_list_pinned,
        "rollback": cmd_rollback,
    }[args.command](args)


if __name__ == "__main__":
    main()
