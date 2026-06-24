import os
import json
import shutil
import tarfile
import zipfile
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from . import dpms_fetch
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn
from rich.status import Status
from rich.text import Text
from rich import print as rich_print
from .dpms_progress import Progress as CustomProgress, Spinner
from .dpms_confirm import delete as confirm_delete

console = Console()

from . import config
from . import dpms_logging
from . import dpms_history
INSTALL_ROOT_DIR = config.INSTALL_ROOT_DIR
REPOSITORY_DIR = config.REPOSITORY_DIR
DP_DB_DIR = config.DP_DB_DIR
DPMS_ARCH = config.DPMS_ARCH
IS_MACOS = config.IS_MACOS
IS_ROOT = config.IS_ROOT
PRIV_ESCALATOR = config.PRIV_ESCALATOR
needs_privileges = config.needs_privileges
reexec_with_privileges = config.reexec_with_privileges

log = dpms_logging.get_logger("dpms")

from .dpms_errors import (
    Error as DPMSCoreError, InvalidSourceError, UnsupportedCompressionError,
    SubprocessError, NetworkError, ArchiveError,
)


def _read_package_metadata_from_dir(package_dir):
    meta_file = os.path.join(package_dir, 'package.json')
    if os.path.exists(meta_file):
        try:
            with open(meta_file, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            rich_print(f"[yellow]Warning: Malformed package.json in {package_dir}: {e}[/yellow]")
            return None
    return None


def _parse_version(version_str):
    if version_str is None:
        return (0,)
    try:
        parts = []
        for part in version_str.split('.'):
            digits = ''
            for ch in part:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            parts.append(int(digits) if digits else 0)
        return tuple(parts)
    except (ValueError, AttributeError):
        return (0,)


def _parse_installed_version(package_name):
    """Read the version of an installed package from its archive name in REPOSITORY_DIR,
    or return (0,) as fallback."""
    list_path = os.path.join(DP_DB_DIR, package_name)
    if not os.path.exists(list_path):
        return None
    if os.path.exists(REPOSITORY_DIR):
        for f in sorted(os.listdir(REPOSITORY_DIR), reverse=True):
            if f.startswith(package_name + '-'):
                parsed = _parse_package_archive_name(f)
                if parsed and parsed[0]:
                    return parsed[1]
    return None


def _parse_package_archive_name(filename):
    match = re.match(
        r'(.+?)-([0-9][\w.]*)(?:-(\w+))?\.dp-(rc\d+)\.tar\.xz$',
        filename, re.IGNORECASE
    )
    if match:
        return match.group(1), _parse_version(match.group(2)), match.group(4), match.group(3)

    match = re.match(
        r'(.+?)-([0-9][\w.]*)(?:-(\w+))?\.dp\.tar\.xz$',
        filename, re.IGNORECASE
    )
    if match:
        return match.group(1), _parse_version(match.group(2)), None, match.group(3)

    match = re.match(
        r'(.+?)-([0-9][\w.]*)\.(dpm|zip|tar(?:\.gz|\.bz2|\.xz)?|tgz|tbz2|txz)$',
        filename, re.IGNORECASE
    )
    if match:
        return match.group(1), _parse_version(match.group(2)), None, None

    return None, None, None, None


def make_tar(source_path, output_filename, compression_type='gz', status_widget=None, verbose=False):
    def log_status(message, style="white"):
        if status_widget:
            status_widget.update(Text(message, style=style))
        else:
            rich_print(f"[{style}]{message}[/{style}]")

    if verbose:
        log_status(f"[bold cyan]Verbose mode enabled.[/bold cyan]")

    if not os.path.exists(source_path):
        raise InvalidSourceError(f"The source path '{source_path}' does not exist.")

    compression_type = compression_type.lower()
    
    if compression_type not in ['gz', 'xz']:
        raise UnsupportedCompressionError(f"Invalid compression type '{compression_type}'. Use 'gz' or 'xz'.")
    
    if compression_type == 'gz':
        archive_filename = f"{output_filename}.tar.gz"
        try:
            if verbose:
                log_status(f"Using tarfile module for gzip compression.", style="dim")
            
            with Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeRemainingColumn(),
                console=console
            ) as progress:
                total_files = 0
                if os.path.isfile(source_path):
                    total_files = 1
                elif os.path.isdir(source_path):
                    for _, _, files in os.walk(source_path):
                        total_files += len(files)
                
                task = progress.add_task(f"[cyan]Compressing to {archive_filename}", total=total_files)
                
                with tarfile.open(archive_filename, 'w:gz') as tar:
                    for root, _, files in os.walk(source_path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            tar.add(file_path, arcname=os.path.relpath(file_path, os.path.dirname(source_path)))
                            progress.update(task, advance=1)
            
            log_status(f"Successfully compressed '{source_path}' into '{archive_filename}' using gzip.", style="bold green")
        except Exception as e:
            raise DPMSCoreError(f"An error occurred during gzip compression: {e}")

    elif compression_type == 'xz':
        archive_filename = f"{output_filename}.tar.xz"

        try:
            if verbose:
                log_status(f"Compressing to {archive_filename} using xz (Python tarfile)...", style="dim")

            with Status("[bold green]Compressing...[/bold green]", console=console) as status:
                total_files = 0
                if os.path.isfile(source_path):
                    total_files = 1
                elif os.path.isdir(source_path):
                    for _, _, files in os.walk(source_path):
                        total_files += len(files)

                with tarfile.open(archive_filename, 'w:xz') as tar:
                    for root, _, files in os.walk(source_path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            tar.add(file_path, arcname=os.path.relpath(file_path, os.path.dirname(source_path)))

            log_status(f"Successfully compressed '{source_path}' into '{archive_filename}' using xz.", style="bold green")
        except Exception as e:
            raise DPMSCoreError(f"An error occurred during xz compression: {e}")


def download_file(url, output_path, verbose=False):
    if verbose:
        console.print(f"[dim][bold cyan]Attempting to download from:[/bold cyan] [link={url}]{url}[/link][/dim]")

    log.info(f"Downloading {os.path.basename(output_path)}")

    try:
        spinner = Spinner(f"Connecting to {url.split('/')[2] if '://' in url else url}")
        for _ in range(6):
            spinner.spin()
            time.sleep(0.05)

        u = dpms_fetch.fetch_parse_url(url)
        if not u:
            spinner.fail("Couldn't parse URL")
            raise NetworkError(f"Couldn't parse URL: {url}")

        resp = dpms_fetch.fetch_xget(u)
        spinner.done("Connected")

        total_size = 0
        try:
            total_size = int(resp.headers.get('Content-Length', 0))
        except (ValueError, AttributeError):
            total_size = 0

        downloaded = 0

        bar = CustomProgress(total=total_size or None,
                              label=f"Downloading {os.path.basename(output_path)[:18]}")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or '.', exist_ok=True)
        with open(output_path, 'wb') as f:
            while True:
                data = resp.read(8192)
                if not data:
                    break
                f.write(data)
                downloaded += len(data)
                if total_size:
                    bar.update(downloaded)
                else:
                    bar.tick()

        if not total_size:
            bar.update(downloaded)

        console.print(f"[bold green]Successfully downloaded[/bold green] to '{output_path}'.")
        log.debug(f"Downloaded {total_size} bytes to {output_path}")

    except NetworkError:
        raise
    except Exception as e:
        raise NetworkError(f"Download failed: {e}")


def _safe_extract_member(member, destination_dir):
    member_path = os.path.normpath(member.name)
    if member_path.startswith(("..", "/")):
        raise ArchiveError(f"Path traversal blocked: {member.name}")
    dest = os.path.join(destination_dir, member_path)
    if not dest.startswith(os.path.normpath(destination_dir)):
        raise ArchiveError(f"Path traversal blocked: {member.name}")

def extract_archive(archive_path, destination_dir, verbose=False):
    if not os.path.exists(archive_path):
        raise InvalidSourceError(f"The archive '{archive_path}' does not exist.")

    os.makedirs(destination_dir, exist_ok=True)

    try:
        if tarfile.is_tarfile(archive_path):
            with tarfile.open(archive_path) as tar:
                members = tar.getmembers()
                total = len(members)

            bar = CustomProgress(total=total, label="Extracting")

            with tarfile.open(archive_path) as tar:
                for i, member in enumerate(members, 1):
                    _safe_extract_member(member, destination_dir)
                    tar.extract(member, path=destination_dir)
                    bar.update(i)

        elif zipfile.is_zipfile(archive_path):
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                members = zip_ref.namelist()
                total = len(members)

            bar = CustomProgress(total=total, label="Extracting")

            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                for i, name in enumerate(members, 1):
                    member_path = os.path.normpath(name)
                    if member_path.startswith(("..", "/")):
                        raise ArchiveError(f"Path traversal blocked: {name}")
                    dest = os.path.join(destination_dir, member_path)
                    if not dest.startswith(os.path.normpath(destination_dir)):
                        raise ArchiveError(f"Path traversal blocked: {name}")
                    zip_ref.extract(name, destination_dir)
                    bar.update(i)

        else:
            raise ArchiveError(f"Unsupported archive format for '{archive_path}'. Only .tar.gz, .tar.xz, .zip, and .dp.tar.xz are supported.")

        rich_print(f"[bold green]Successfully extracted[/bold green] to '{destination_dir}'.")

    except (tarfile.TarError, zipfile.BadZipFile, IOError) as e:
        raise ArchiveError(f"Couldn't extract archive: {e}")
    except Exception as e:
        raise DPMSCoreError(f"An unexpected error occurred during extraction: {e}")

REPO_CACHE_DIR = os.path.join(os.path.expanduser('~'), '.cache', 'dpms', 'repos')


def _sync_git_repo(name, url):
    repo_dir = os.path.join(REPO_CACHE_DIR, name)
    if os.path.isdir(os.path.join(repo_dir, '.git')):
        try:
            r = subprocess.run(['git', '-C', repo_dir, 'pull', '--ff-only'],
                               capture_output=True, timeout=30)
            if r.returncode != 0:
                log.error(f"git pull failed for '{name}': {r.stderr.decode()}")
            else:
                log.debug(f"Pulled repo '{name}'")
        except Exception as e:
            log.error(f"Couldn't sync repo '{name}': {e}")
    else:
        os.makedirs(REPO_CACHE_DIR, exist_ok=True)
        try:
            r = subprocess.run(['git', 'clone', url, repo_dir],
                               capture_output=True, timeout=60)
            if r.returncode != 0:
                raise DPMSCoreError(f"Couldn't clone repo '{name}': {r.stderr.decode()}")
            log.info(f"Cloned repo '{name}' from {url}")
        except Exception as e:
            log.error(f"Couldn't sync repo '{name}': {e}")
            raise DPMSCoreError(f"Couldn't clone repo '{name}' from {url}: {e}")
    return repo_dir


def _find_package_in_repos(package_name, verbose=False):
    repo_list = load_repo_list()
    best_match = None
    best_ver = (0,)
    for name, info in repo_list.items():
        if not info.get('enabled', True):
            continue
        url = info.get('url', '')
        if not url.endswith('.git'):
            continue
        if verbose:
            rich_print(f"[bold blue]Searching in repo '{name}'...[/bold blue]")
        try:
            repo_dir = _sync_git_repo(name, url)
            for f in os.listdir(repo_dir):
                if not f.startswith(package_name + '-'):
                    continue
                if not (f.endswith('.dp.tar.xz') or f.endswith('.tar.xz') or f.endswith('.tar.gz') or f.endswith('.dpm')):
                    continue
                parsed = _parse_package_archive_name(f)
                if parsed and parsed[0] == package_name:
                    ver = parsed[1]
                    _, _, _, arch = parsed
                    if arch == DPMS_ARCH and ver > best_ver:
                        best_match = os.path.join(repo_dir, f)
                        best_ver = ver
                    elif arch != DPMS_ARCH and best_match is None:
                        best_match = os.path.join(repo_dir, f)
                        best_ver = ver
        except Exception as e:
            if verbose:
                rich_print(f"[yellow]  repo '{name}' error: {e}[/yellow]")
            continue
    return best_match


def install_package(package_arg, verbose=False):
    archive_path = None
    cleanup = False
    spinner = None

    try:
        if os.path.isfile(package_arg):
            archive_path = package_arg
            console.print(f"[bold blue]Installing from local file:[/bold blue] {archive_path}")
        elif '://' in package_arg:
            archive_filename = package_arg.split('/')[-1]
            archive_path = os.path.join(os.path.expanduser('~'), 'dpms_temp', archive_filename)
            os.makedirs(os.path.dirname(archive_path), exist_ok=True)
            cleanup = True
            console.print(f"[bold blue]Downloading[/bold blue] [link={package_arg}]{archive_filename}[/link]...")
            download_file(package_arg, archive_path, verbose=verbose)
        else:
            found = None
            if os.path.isdir(REPOSITORY_DIR):
                for f in sorted(os.listdir(REPOSITORY_DIR), reverse=True):
                    if f.startswith(package_arg + '-'):
                        parsed = _parse_package_archive_name(f)
                        if parsed and parsed[0]:
                            _, _, _, arch = parsed
                            if arch == DPMS_ARCH:
                                found = f
                                break
                            if arch != DPMS_ARCH and found is None:
                                found = f
            if found:
                archive_path = os.path.join(REPOSITORY_DIR, found)
                console.print(f"[bold blue]Found in local repository:[/bold blue] {found}")
            else:
                spinner = Spinner(f"Searching for '{package_arg}' in repos")
                for _ in range(8):
                    spinner.spin()
                    time.sleep(0.08)
                repo_archive = _find_package_in_repos(package_arg, verbose=verbose)
                if repo_archive:
                    archive_path = repo_archive
                    spinner.done(f"Found {os.path.basename(archive_path)}")
                else:
                    spinner.fail(f"Package '{package_arg}' not found")
                    raise InvalidSourceError(f"Package '{package_arg}' not found in {REPOSITORY_DIR} or any git repository")
            spinner = None

        log.info(f"Installing {os.path.basename(archive_path)}")

        archive_filename = os.path.basename(archive_path)
        parsed = _parse_package_archive_name(archive_filename)
        if not parsed or not parsed[0]:
            if cleanup:
                os.remove(archive_path)
            raise ArchiveError(f"Could not determine package name from '{archive_filename}'.")

        package_name, version, rc, arch = parsed

        extract_spinner = Spinner(f"Reading {os.path.basename(archive_path)}")
        for _ in range(4):
            extract_spinner.spin()
            time.sleep(0.05)

        file_list = []
        try:
            with tarfile.open(archive_path, 'r:*') as tar:
                for m in tar.getmembers():
                    name = m.name
                    if os.path.isabs(name):
                        name = os.path.normpath(name.lstrip('/'))
                    if '..' in name.split(os.sep):
                        if cleanup:
                            os.remove(archive_path)
                        raise ArchiveError(f"Archive contains path traversal: {m.name}")
                    file_list.append(name)
        except Exception as e:
            if cleanup:
                os.remove(archive_path)
            raise ArchiveError(f"Failed to read archive contents: {e}")

        log.debug(f"Extracting {len(file_list)} entries from {os.path.basename(archive_path)}")

        total = len(file_list)
        extract_spinner.done(f"Extracting {total} files")
        bar = CustomProgress(total=total, label=f"Installing {package_name}")

        with tarfile.open(archive_path, 'r:*') as tar:
            for i, m in enumerate(tar.getmembers(), 1):
                name = m.name
                if os.path.isabs(name):
                    name = os.path.normpath(name.lstrip('/'))
                if '..' in name.split(os.sep):
                    if cleanup:
                        os.remove(archive_path)
                    raise ArchiveError(f"Archive contains path traversal: {m.name}")
                m.name = name
                tar.extract(m, path=INSTALL_ROOT_DIR)
                bar.update(i)

        if not file_list:
            rich_print(f"[yellow]Warning: Archive '{archive_filename}' contains no files.[/yellow]")

        db_dir = DP_DB_DIR
        os.makedirs(db_dir, exist_ok=True)
        list_path = os.path.join(db_dir, package_name)
        with open(list_path, 'w') as f:
            for path in file_list:
                f.write(os.path.join(INSTALL_ROOT_DIR, path) + '\n')

        if cleanup:
            os.remove(archive_path)
            if verbose:
                rich_print(f"[dim]Removed temporary file:[/dim] {archive_path}")

        rich_print(f"[bold green]Installation complete![/bold green] Package '{package_name}' installed ({len(file_list)} files tracked).")
        log.info(f"Package '{package_name}' installed ({len(file_list)} files)")
        version_str = ".".join(str(v) for v in version) if version else ""
        dpms_history.record("install", package_name, version=version_str, files_count=len(file_list))
    except Exception as e:
        log.error(f"Install failed: {e}")
        raise


def list_installed():
    db_dir = DP_DB_DIR
    if not os.path.exists(db_dir):
        rich_print("[yellow]No packages installed yet.[/yellow]")
        return

    installed = sorted(os.listdir(db_dir))

    if not installed:
        rich_print("[yellow]No packages installed yet.[/yellow]")
        return

    from rich.table import Table
    table = Table(title="Installed Packages")
    table.add_column("Package", style="bold green")
    table.add_column("Files")
    for pkg in installed:
        list_path = os.path.join(db_dir, pkg)
        count = 0
        try:
            with open(list_path) as f:
                count = sum(1 for _ in f)
        except Exception:
            pass
        table.add_row(pkg, str(count))

    legacy_dir = os.path.expanduser('~/system_root')
    if os.path.exists(legacy_dir):
        legacy = [d for d in os.listdir(legacy_dir)
                  if os.path.isdir(os.path.join(legacy_dir, d)) and d != 'var']
        for pkg in sorted(legacy):
            table.add_row(pkg, "(legacy dir)")

    Console().print(table)


def package_info(package_name):
    from rich.table import Table
    from rich.console import Console
    console = Console()

    repo = load_repo_list()
    table = Table(title=f"Package: {package_name}")
    table.add_column("Field", style="bold green")
    table.add_column("Value")

    if package_name in repo:
        info = repo[package_name]
        table.add_row("Source", "repository")
        table.add_row("Name", package_name)
        table.add_row("Version", info.get("version", "?"))
        table.add_row("Description", info.get("description", ""))
        table.add_row("URL", info.get("url", ""))
        status = "enabled" if info.get("enabled", True) else "disabled"
        table.add_row("Status", status)
    else:
        table.add_row("Source", "[yellow]not in repo[/yellow]")

    list_path = os.path.join(DP_DB_DIR, package_name)
    if os.path.exists(list_path):
        try:
            with open(list_path) as f:
                count = sum(1 for _ in f)
            table.add_row("Installed", "yes")
            table.add_row("Files tracked", str(count))
        except Exception:
            table.add_row("Installed", "[yellow]db read error[/yellow]")
    else:
        table.add_row("Installed", "no")

    console.print(table)


def list_package_files(package_name):
    list_path = os.path.join(DP_DB_DIR, package_name)
    if not os.path.exists(list_path):
        rich_print(f"[yellow]Package '{package_name}' is not installed or has no file list.[/yellow]")
        return

    try:
        with open(list_path) as f:
            files = [line.strip() for line in f if line.strip()]
    except Exception as e:
        rich_print(f"[red]Failed to read file list: {e}[/red]")
        return

    if not files:
        rich_print(f"[yellow]No files tracked for '{package_name}'.[/yellow]")
        return

    from rich.table import Table
    from rich.console import Console
    console = Console()
    table = Table(title=f"Files installed by '{package_name}' ({len(files)})")
    table.add_column("#", style="dim")
    table.add_column("Path")
    for i, fp in enumerate(files, 1):
        exists = os.path.exists(fp)
        icon = "[green]\u2713[/green]" if exists else "[red]\u2717[/red]"
        table.add_row(str(i), f"{icon} {fp}")
    console.print(table)


def verify_package(package_name):
    list_path = os.path.join(DP_DB_DIR, package_name)
    if not os.path.exists(list_path):
        rich_print(f"[yellow]Package '{package_name}' is not installed.[/yellow]")
        return

    try:
        with open(list_path) as f:
            files = [line.strip() for line in f if line.strip()]
    except Exception as e:
        rich_print(f"[red]Failed to read file list: {e}[/red]")
        return

    if not files:
        rich_print(f"[yellow]No files tracked for '{package_name}'.[/yellow]")
        return

    missing = []
    found = []
    for fp in files:
        if os.path.exists(fp):
            found.append(fp)
        else:
            missing.append(fp)

    from rich.table import Table
    from rich.console import Console
    from rich import box
    console = Console()
    table = Table(title=f"Verification: '{package_name}'", box=box.ROUNDED)
    table.add_column("Result", style="bold")
    table.add_column("Count")
    table.add_column("Status")
    total = len(files)
    table.add_row("Total files", str(total), "")
    table.add_row("Present", str(len(found)), "[green]\u2713[/green]")
    table.add_row("Missing", str(len(missing)), "[red]\u2717[/red]" if missing else "[green]none[/green]")
    console.print(table)

    if missing:
        rich_print(f"\n[red]Missing files:[/red]")
        for fp in missing:
            rich_print(f"  [red]\u2717 {fp}[/red]")

    return len(missing) == 0


def show_installable():
    repo = load_repo_list()
    if not repo:
        rich_print("[yellow]No repositories configured. Add some to repo_list.json[/yellow]")
        return

    from rich.table import Table
    table = Table(title="Installable Packages")
    table.add_column("Package", style="bold green")
    table.add_column("Version", style="cyan")
    table.add_column("Description")
    for name, info in repo.items():
        table.add_row(name, info.get('version', '?'), info.get('description', ''))
    Console().print(table)


def create_tar(folder, output_filename=None, compression_type='xz'):
    if output_filename is None:
        output_filename = folder.name if hasattr(folder, 'name') else os.path.basename(folder)
    make_tar(str(folder), str(output_filename), compression_type)


def make_dp_archive(folder, name=None, version=None, arch=None, rc=None):
    folder = Path(folder)
    if not folder.exists() or not folder.is_dir():
        raise InvalidSourceError(f"'{folder}' is not a valid directory.")

    if name and version:
        pkg_name = name
        pkg_version = version
    else:
        pkg_meta = _read_package_metadata_from_dir(str(folder))
        if pkg_meta and 'name' in pkg_meta and 'version' in pkg_meta:
            pkg_name = pkg_meta['name']
            pkg_version = pkg_meta['version']
        else:
            match = re.match(r'^(.+)-(\d+(?:\.\d+)*)(?:-rc\d+)?$', folder.name)
            if match:
                pkg_name = match.group(1)
                pkg_version = match.group(2)
            else:
                pkg_name = folder.name
                pkg_version = "0.0.0"

    parts = [pkg_name, pkg_version]
    if arch:
        parts.append(arch)
    else:
        parts.append(DPMS_ARCH)
    base = "-".join(parts)

    if rc:
        archive_name = f"{base}.dp-rc{rc}.tar.xz"
    else:
        archive_name = f"{base}.dp.tar.xz"

    archive_path = folder.parent / archive_name

    with tarfile.open(str(archive_path), 'w:xz') as tar:
        for entry in sorted(folder.iterdir()):
            tar.add(str(entry), arcname=entry.name)

    rich_print(f"[bold green]Created package: {archive_name}[/bold green]")
    return str(archive_name)


REPO_LIST_FILE = os.path.join(
    os.environ.get('DPMS_DATA_DIR',
        os.path.join(os.path.expanduser('~'), '.cache', 'dpms')),
    'repo_list.json')


def _init_default_repo_list():
    if os.path.exists(REPO_LIST_FILE):
        return
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    default = os.path.join(pkg_dir, 'repo_list.json')
    if os.path.exists(default):
        try:
            os.makedirs(os.path.dirname(REPO_LIST_FILE), exist_ok=True)
            with open(default) as src, open(REPO_LIST_FILE, 'w') as dst:
                json.dump(json.load(src), dst, indent=2)
        except Exception:
            pass


_init_default_repo_list()


def save_repo_list(repo_list):
    try:
        os.makedirs(os.path.dirname(REPO_LIST_FILE), exist_ok=True)
        with open(REPO_LIST_FILE, 'w') as f:
            json.dump(repo_list, f, indent=2)
        return True
    except Exception:
        return False


def load_repo_list():
    if os.path.exists(REPO_LIST_FILE):
        try:
            with open(REPO_LIST_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}


def search_package(query, verbose=False):
    if verbose:
        rich_print(f"[bold cyan]Searching for '{query}'...[/bold cyan]")

    repo = load_repo_list()
    results = []

    for name, info in repo.items():
        if query.lower() in name.lower():
            results.append((name, info))

    if results:
        from rich.table import Table
        from rich.console import Console
        console = Console()
        table = Table(title=f"Search results for '{query}'")
        table.add_column("Package", style="bold green")
        table.add_column("Version", style="cyan")
        table.add_column("Description")
        for name, info in results:
            table.add_row(name, info.get('version', '?'), info.get('description', ''))
        console.print(table)
    else:
        rich_print(f"[yellow]No packages found matching '{query}'.[/yellow]")

    return results


def remove_package(package_name, verbose=False):
    log.info(f"Removing package '{package_name}'")
    list_path = os.path.join(DP_DB_DIR, package_name)

    if os.path.exists(list_path):
        try:
            with open(list_path) as f:
                files = [line.strip() for line in f if line.strip()]
        except Exception as e:
            rich_print(f"[red]Failed to read file list for '{package_name}': {e}[/red]")
            return False

        bar = CustomProgress(total=len(files), label="Removing")
        removed = 0
        for i, fp in enumerate(files, 1):
            try:
                if os.path.exists(fp) or os.path.islink(fp):
                    if os.path.isdir(fp) and not os.path.islink(fp):
                        shutil.rmtree(fp)
                    else:
                        os.remove(fp)
                    removed += 1
                    if verbose:
                        rich_print(f"[dim]  removed {fp}[/dim]")
            except Exception as e:
                if verbose:
                    rich_print(f"[yellow]  could not remove {fp}: {e}[/yellow]")
            bar.update(i)

        dirs = set()
        for fp in files:
            d = os.path.dirname(fp)
            while d and d != '/':
                dirs.add(d)
                d = os.path.dirname(d)
        for d in sorted(dirs, reverse=True):
            try:
                if os.path.isdir(d) and not os.listdir(d):
                    os.rmdir(d)
                    if verbose:
                        rich_print(f"[dim]  removed empty dir {d}[/dim]")
            except Exception:
                pass

        os.remove(list_path)
        rich_print(f"[bold green]Package '{package_name}' removed successfully.[/bold green] ({removed} files)")
        log.info(f"Package '{package_name}' removed ({removed} files)")
        dpms_history.record("remove", package_name, files_count=removed)
        return True

    install_dir = os.path.join(os.path.expanduser('~/system_root'), package_name)
    if os.path.exists(install_dir):
        try:
            shutil.rmtree(install_dir)
            rich_print(f"[bold green]Package '{package_name}' removed successfully (legacy).[/bold green]")
            log.info(f"Package '{package_name}' removed (legacy)")
            dpms_history.record("remove", package_name, detail="legacy")
            return True
        except Exception as e:
            rich_print(f"[red]Failed to remove legacy package '{package_name}': {e}[/red]")
            return False

    rich_print(f"[red]Package '{package_name}' is not installed.[/red]")
    return False


uninstall_package = remove_package


def rescue_mode():
    from .dpms_rescue import run_rescue_tui
    run_rescue_tui()


def download_package(package_arg, dest_dir=None, verbose=False):
    if dest_dir is None:
        dest_dir = os.path.join(os.path.expanduser('~'), 'dpms_temp')
    os.makedirs(dest_dir, exist_ok=True)

    archive_path = None
    if os.path.isfile(package_arg):
        rich_print(f"[yellow]'{package_arg}' already exists locally.[/yellow]")
        return package_arg
    elif '://' in package_arg:
        archive_filename = package_arg.split('/')[-1]
        archive_path = os.path.join(dest_dir, archive_filename)
        rich_print(f"[bold blue]Downloading[/bold blue] [link={package_arg}]{package_arg}[/link]...")
        download_file(package_arg, archive_path, verbose=verbose)
    else:
        rich_print(f"[bold blue]Searching for[/bold blue] {package_arg}...")
        repo_archive = _find_package_in_repos(package_arg, verbose=verbose)
        if not repo_archive:
            raise InvalidSourceError(f"Package '{package_arg}' not found in any repository.")
        import shutil
        archive_path = os.path.join(dest_dir, os.path.basename(repo_archive))
        shutil.copy2(repo_archive, archive_path)
        rich_print(f"[green]Downloaded[/green] {os.path.basename(archive_path)}")

    return archive_path


def downgrade_package(package_name, verbose=False, dry_run=False):
    """Downgrade a package to the next older version available in repos."""
    list_path = os.path.join(DP_DB_DIR, package_name)
    if not os.path.exists(list_path):
        raise InvalidSourceError(f"Package '{package_name}' is not installed.")

    repo_list = load_repo_list()
    candidates = []
    for name, info in repo_list.items():
        if not info.get('enabled', True):
            continue
        url = info.get('url', '')
        if not url.endswith('.git'):
            continue
        try:
            repo_dir = _sync_git_repo(name, url)
            for f in os.listdir(repo_dir):
                if f.startswith(package_name + '-'):
                    parsed = _parse_package_archive_name(f)
                    if parsed and parsed[0]:
                        pname, ver, rc, arch = parsed
                        pass  # accept any arch
                        candidates.append((ver, os.path.join(repo_dir, f), rc, arch))
        except Exception:
            continue

    if not candidates:
        raise InvalidSourceError(f"No versions of '{package_name}' found in any repo.")

    candidates.sort(key=lambda x: x[0], reverse=True)
    if len(candidates) <= 1:
        raise InvalidSourceError(f"Only one version of '{package_name}' available, nothing to downgrade to.")

    target = candidates[1] if len(candidates) > 1 else None
    if not target:
        raise InvalidSourceError(f"No older version of '{package_name}' found.")

    target_ver_str = ".".join(str(v) for v in target[0])
    rich_print(f"[bold blue]Downgrading[/bold blue] {package_name} to {target_ver_str}...")

    if dry_run:
        rich_print(f"[yellow]DRY RUN:[/yellow] Would remove {package_name} and install version {target_ver_str}")
        return

    list_path = os.path.join(DP_DB_DIR, package_name)
    rollback_files = []
    if os.path.exists(list_path):
        with open(list_path) as f:
            rollback_files = [l.strip() for l in f if l.strip()]

    remove_package(package_name, verbose=verbose)
    archive_path = target[1]
    try:
        _install_from_archive(archive_path, verbose=verbose)
    except Exception:
        rich_print(f"[red]Downgrade failed, restoring previous version...[/red]")
        if rollback_files:
            # restore old DB entry
            db_dir = DP_DB_DIR
            os.makedirs(db_dir, exist_ok=True)
            with open(os.path.join(db_dir, package_name), 'w') as f:
                for path in rollback_files:
                    if os.path.exists(path):
                        f.write(path + '\n')
            rich_print(f"[yellow]Restored file list for {package_name} "
                       f"({len(rollback_files)} entries).[/yellow]")
        raise


def _install_from_archive(archive_path, verbose=False):
    """Install a package from a specific archive path (internal helper)."""
    archive_filename = os.path.basename(archive_path)
    parsed = _parse_package_archive_name(archive_filename)
    if not parsed or not parsed[0]:
        raise ArchiveError(f"Could not determine package name from '{archive_filename}'.")

    package_name, version, rc, arch = parsed
    console.print(f"[bold blue]Installing[/bold blue] {package_name}...")

    sp = Spinner(f"Reading {os.path.basename(archive_path)}")
    for _ in range(4):
        sp.spin()
        time.sleep(0.05)

    file_list = []
    try:
        with tarfile.open(archive_path, 'r:*') as tar:
            for m in tar.getmembers():
                name = m.name
                if os.path.isabs(name):
                    name = os.path.normpath(name.lstrip('/'))
                if '..' in name.split(os.sep):
                    raise ArchiveError(f"Archive contains path traversal: {m.name}")
                file_list.append(name)
    except Exception as e:
        raise ArchiveError(f"Failed to read archive: {e}")

    total = len(file_list)
    sp.done(f"Extracting {total} files")
    bar = CustomProgress(total=total, label=f"Installing {package_name}")
    throttle = max(total // 100, 1)
    with tarfile.open(archive_path, 'r:*') as tar:
        for i, m in enumerate(tar.getmembers(), 1):
            if os.path.isabs(m.name):
                m.name = os.path.normpath(m.name.lstrip('/'))
            if m.name.startswith('/') or '..' in m.name.split(os.sep):
                continue
            tar.extract(m, path=INSTALL_ROOT_DIR)
            if i % throttle == 0 or i == total:
                bar.update(i)

    db_dir = DP_DB_DIR
    os.makedirs(db_dir, exist_ok=True)
    list_path = os.path.join(db_dir, package_name)
    with open(list_path, 'w') as f:
        for path in file_list:
            f.write(os.path.join(INSTALL_ROOT_DIR, path) + '\n')

    rich_print(f"[bold green]Done.[/bold green] {package_name} installed ({len(file_list)} files).")
    version_str = ".".join(str(v) for v in version) if version else ""
    dpms_history.record("downgrade", package_name, version=version_str, files_count=len(file_list))


def reinstall_package(package_name, verbose=False):
    list_path = os.path.join(DP_DB_DIR, package_name)
    if not os.path.exists(list_path):
        raise InvalidSourceError(f"Package '{package_name}' is not installed.")

    rich_print(f"[bold blue]Reinstalling[/bold blue] {package_name}...")
    remove_package(package_name, verbose=verbose)
    install_package(package_name, verbose=verbose)


def _read_package_depends(archive_path):
    """Read dependency list from a package archive's metadata."""
    try:
        with tarfile.open(archive_path, 'r:*') as tar:
            for m in tar.getmembers():
                if m.name.endswith('package.json') or m.name.endswith('DEPENDS'):
                    f = tar.extractfile(m)
                    if not f:
                        continue
                    meta = f.read().decode('utf-8', errors='replace')
                    f.close()
                    try:
                        j = json.loads(meta)
                        deps = j.get('depends', j.get('dependencies', []))
                        return [d.split()[0] if isinstance(d, str) else d.get('name', str(d)) for d in deps]
                    except json.JSONDecodeError:
                        return [l.strip() for l in meta.splitlines() if l.strip() and not l.startswith('#')]
    except Exception:
        return None


def clean_orphaned(verbose=False):
    db_dir = DP_DB_DIR
    if not os.path.exists(db_dir):
        rich_print("[yellow]No packages installed.[/yellow]")
        return

    installed = set(os.listdir(db_dir))
    if not installed:
        rich_print("[yellow]No packages installed.[/yellow]")
        return

    rich_print("[bold blue]Scanning for orphaned packages...[/bold blue]")
    depended = {pkg: False for pkg in installed}
    for pkg in installed:
        archive = _find_package_in_repos(pkg, verbose=False)
        if not archive:
            continue
        deps = _read_package_depends(archive)
        if not deps:
            continue
        for dep in deps:
            if dep in depended:
                depended[dep] = True

    orphans = [pkg for pkg in sorted(installed) if not depended[pkg]]

    if not orphans:
        rich_print("[green]No orphaned packages found.[/green]")
        return

    rich_print(f"[yellow]Found {len(orphans)} orphaned package(s):[/yellow]")
    for pkg in orphans:
        rich_print(f"  [bold]{pkg}[/bold]")

    if confirm_delete():
        for pkg in orphans:
            try:
                remove_package(pkg, verbose=verbose)
                rich_print(f"  [red]removed[/red] {pkg}")
            except Exception as e:
                rich_print(f"  [red]failed[/red] {pkg}: {e}")


def show_depends(package_name, depth=0, max_depth=3, seen=None, verbose=False):
    if seen is None:
        seen = set()
    if package_name in seen or depth > max_depth:
        return
    seen.add(package_name)

    prefix = "  " * depth
    if depth > 0:
        rich_print(f"{prefix}[dim]\u2514[/dim] [bold]{package_name}[/bold]")
    else:
        rich_print(f"[bold]{package_name}[/bold]")

    repo_archive = None
    try:
        repo_archive = _find_package_in_repos(package_name, verbose=False)
    except Exception:
        pass

    if repo_archive:
        try:
            with tarfile.open(repo_archive, 'r:*') as tar:
                meta = None
                for m in tar.getmembers():
                    if m.name.endswith('package.json') or m.name.endswith('DEPENDS'):
                        f = tar.extractfile(m)
                        if f:
                            meta = f.read().decode('utf-8', errors='replace')
                            f.close()
                        break
                if meta:
                    try:
                        j = json.loads(meta)
                        deps = j.get('depends', j.get('dependencies', []))
                    except json.JSONDecodeError:
                        deps = [l.strip() for l in meta.splitlines() if l.strip() and not l.startswith('#')]
                    for dep in deps:
                        if isinstance(dep, str):
                            dep_name = dep.split()[0] if dep.split() else dep
                        elif isinstance(dep, dict):
                            dep_name = dep.get('name', str(dep))
                        else:
                            continue
                        show_depends(dep_name, depth + 1, max_depth, seen, verbose)
        except Exception as e:
            if verbose:
                rich_print(f"{prefix}  [red]error reading metadata:[/red] {e}")


def show_rdepends(package_name, verbose=False):
    db_dir = DP_DB_DIR
    if not os.path.exists(db_dir):
        rich_print("[yellow]No packages installed.[/yellow]")
        return

    list_path = os.path.join(db_dir, package_name)
    if not os.path.exists(list_path):
        rich_print(f"[yellow]Package '{package_name}' is not installed.[/yellow]")
        return

    rdeps = []
    for pkg in sorted(os.listdir(db_dir)):
        if pkg == package_name:
            continue
        archive = _find_package_in_repos(pkg, verbose=False)
        if not archive:
            continue
        deps = _read_package_depends(archive)
        if deps and package_name in deps:
            rdeps.append(pkg)

    if not rdeps:
        rich_print(f"[green]No packages depend on[/green] [bold]{package_name}[/bold].")
    else:
        rich_print(f"[bold]{package_name}[/bold] is required by:")
        for pkg in rdeps:
            rich_print(f"  [bold]{pkg}[/bold]")


def what_owns(file_path, verbose=False):
    db_dir = DP_DB_DIR
    if not os.path.exists(db_dir):
        rich_print("[yellow]No packages installed.[/yellow]")
        return

    file_path = os.path.abspath(os.path.expanduser(file_path))
    owners = []
    for pkg in sorted(os.listdir(db_dir)):
        list_path = os.path.join(db_dir, pkg)
        try:
            with open(list_path) as f:
                for line in f:
                    if line.rstrip('\n') == file_path:
                        owners.append(pkg)
                        break
        except Exception:
            continue

    if not owners:
        rich_print(f"[yellow]'{file_path}' is not owned by any installed package.[/yellow]")
    else:
        for pkg in owners:
            rich_print(f"[green]{file_path}[/green] is owned by [bold]{pkg}[/bold]")


def check_integrity(verbose=False):
    db_dir = DP_DB_DIR
    if not os.path.exists(db_dir):
        rich_print("[yellow]No packages installed.[/yellow]")
        return

    installed = sorted(os.listdir(db_dir))
    if not installed:
        rich_print("[yellow]No packages installed.[/yellow]")
        return

    total_errors = 0
    for pkg in installed:
        list_path = os.path.join(db_dir, pkg)
        if not os.path.exists(list_path):
            rich_print(f"[red]missing db entry:[/red] {pkg}")
            total_errors += 1
            continue
        try:
            with open(list_path) as f:
                files = [l.rstrip('\n') for l in f if l.strip()]
        except Exception as e:
            rich_print(f"[red]can't read db:[/red] {pkg} \u2014 {e}")
            total_errors += 1
            continue
        missing = [f for f in files if not os.path.exists(f)]
        if missing:
            rich_print(f"[yellow]{pkg}:[/yellow] {len(missing)} missing file(s)")
            if verbose:
                for m in missing:
                    rich_print(f"  [dim]{m}[/dim]")
            total_errors += len(missing)

    if total_errors == 0:
        rich_print("[green]All packages intact.[/green]")
    else:
        rich_print(f"[yellow]{total_errors} issue(s) found.[/yellow]")


def clean_temp_files():
    temp_dir = os.path.join(os.path.expanduser('~'), 'dpms_temp')
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir, exist_ok=True)


def verify_repo_list():
    if not os.path.exists(REPO_LIST_FILE):
        with open(REPO_LIST_FILE, 'w') as f:
            json.dump({}, f)
        return
    try:
        with open(REPO_LIST_FILE, 'r') as f:
            json.load(f)
    except json.JSONDecodeError:
        rich_print(f"[yellow]  Corrupted repo_list.json, resetting[/yellow]")
        with open(REPO_LIST_FILE, 'w') as f:
            json.dump({}, f)


def add_repo(name, url, description="", arch=None):
    repo = load_repo_list()
    if name in repo:
        rich_print(f"[yellow]Repository '{name}' already exists. Use --toggle-repo to enable/disable.[/yellow]")
        return False
    entry = {
        "version": "0.0.0",
        "description": description or f"Repository: {name}",
        "enabled": True,
        "url": url
    }
    if arch:
        entry["arch"] = arch
    repo[name] = entry
    if save_repo_list(repo):
        arch_tag = f" [{arch}]" if arch else ""
        rich_print(f"[bold green]Added repository '{name}'{arch_tag} -> {url}[/bold green]")
        return True
    rich_print("[red]Failed to save repository list.[/red]")
    return False


def remove_repo(name):
    repo = load_repo_list()
    if name not in repo:
        rich_print(f"[yellow]Repository '{name}' not found.[/yellow]")
        return False
    del repo[name]
    if save_repo_list(repo):
        rich_print(f"[bold green]Removed repository '{name}'.[/bold green]")
        return True
    rich_print("[red]Failed to save repository list.[/red]")
    return False


def toggle_repo(name):
    repo = load_repo_list()
    if name not in repo:
        rich_print(f"[yellow]Repository '{name}' not found.[/yellow]")
        return False
    repo[name]["enabled"] = not repo[name].get("enabled", True)
    status = "enabled" if repo[name]["enabled"] else "disabled"
    if save_repo_list(repo):
        rich_print(f"[bold green]{name} is now {status}.[/bold green]")
        return True
    rich_print("[red]Failed to save repository list.[/red]")
    return False


def list_repos(repo_name=None):
    repo = load_repo_list()
    if not repo:
        rich_print("[yellow]No repositories configured.[/yellow]")
        return

    if repo_name:
        if repo_name not in repo:
            rich_print(f"[yellow]Repository '{repo_name}' not found.[/yellow]")
            return
        info = repo[repo_name]
        pkgs = info.get("packages")
        if pkgs:
            from rich.table import Table
            from rich.console import Console
            console = Console()
            table = Table(title=f"Packages from '{repo_name}' ({len(pkgs)})")
            table.add_column("Package", style="bold green")
            for p in sorted(pkgs):
                table.add_row(p)
            console.print(table)
        else:
            from rich.table import Table
            from rich.console import Console
            console = Console()
            table = Table(title=f"Repository: {repo_name}")
            table.add_column("Field", style="bold green")
            table.add_column("Value")
            for key in ("url", "version", "description"):
                if key in info:
                    table.add_row(key.capitalize(), str(info[key]))
            status = "enabled" if info.get("enabled", True) else "disabled"
            table.add_row("Status", status)
            console.print(table)
        return

    from rich.table import Table
    from rich.console import Console
    console = Console()
    table = Table(title="Configured Repositories")
    table.add_column("Name", style="bold green")
    table.add_column("URL")
    table.add_column("Arch", style="cyan")
    table.add_column("Version", style="cyan")
    table.add_column("Status")
    for name, info in repo.items():
        status = "[green]enabled[/green]" if info.get("enabled", True) else "[red]disabled[/red]"
        version = info.get("version", "?")
        arch = info.get("arch") or "[dim]any[/dim]"
        table.add_row(name, info.get("url", ""), arch, version, status)
    console.print(table)


def update_repos():
    repo = load_repo_list()
    if not repo:
        rich_print("[yellow]No repositories configured.[/yellow]")
        return

    total = len([n for n, i in repo.items() if i.get('enabled', True)])
    count = 0
    for name, info in repo.items():
        if not info.get('enabled', True):
            continue
        url = info.get('url', '')
        count += 1
        rich_print(f"[bold blue]({count}/{total})[/bold blue] Syncing [green]{name}[/green]...")
        try:
            if url.endswith('.git'):
                _sync_git_repo(name, url)
            else:
                rich_print(f"  [yellow]not a git repo, skipping pull[/yellow]")
        except Exception as e:
            rich_print(f"  [red]error:[/red] {e}")
    rich_print(f"[bold green]Update complete ({total} repos).[/bold green]")


def upgrade_packages(verbose=False):
    db_dir = DP_DB_DIR
    if not os.path.exists(db_dir):
        rich_print("[yellow]No packages installed.[/yellow]")
        return

    installed = sorted(os.listdir(db_dir))
    if not installed:
        rich_print("[yellow]No packages installed.[/yellow]")
        return

    upgraded = 0
    failed = 0

    for pkg_name in installed:
        rich_print(f"[bold blue]Checking[/bold blue] {pkg_name}...")
        try:
            repo_archive = _find_package_in_repos(pkg_name, verbose=verbose)
            if not repo_archive:
                rich_print(f"  [yellow]not found in any repo[/yellow]")
                continue

            archive_fn = os.path.basename(repo_archive)
            parsed = _parse_package_archive_name(archive_fn)
            if not parsed or not parsed[0]:
                continue
            _, avail_version, _, _ = parsed

            inst_version = _parse_installed_version(pkg_name)
            if inst_version is None:
                continue

            if avail_version and avail_version > inst_version:
                ver_str = '.'.join(str(v) for v in avail_version)
                inst_str = '.'.join(str(v) for v in inst_version)
                rich_print(f"  [green]{inst_str} → {ver_str}[/green]")
                install_package(pkg_name, verbose=verbose)
                upgraded += 1
            else:
                rich_print(f"  [yellow]already up to date[/yellow]")
        except Exception as e:
            rich_print(f"  [red]failed:[/red] {e}")
            failed += 1

    rich_print(f"[bold green]Upgrade complete:[/bold green] {upgraded} upgraded, {failed} failed.")


def sync_repos():
    repo = load_repo_list()
    if not repo:
        rich_print("[yellow]No repositories configured.[/yellow]")
        return

    from rich.console import Console
    from rich.table import Table
    console = Console()
    table = Table(title="Repository Sync Results")
    table.add_column("Name", style="bold green")
    table.add_column("URL")
    table.add_column("Status")
    table.add_column("Response")

    for name, info in repo.items():
        enabled = info.get("enabled", True)
        if not enabled:
            table.add_row(name, info.get("url", ""), "[yellow]skipped[/yellow]", "disabled")
            continue
        url = info.get("url", "")
        try:
            req = urllib.request.Request(url, method='HEAD')
            resp = urllib.request.urlopen(req, timeout=5)
            status = "[green]online[/green]"
            resp_info = f"HTTP {resp.status}"
        except Exception as e:
            status = "[red]offline[/red]"
            resp_info = str(e)[:40]
        table.add_row(name, url, status, resp_info)

    console.print(table)


# ── Export / Import installed ───────────────────────────────────────

def export_installed(filepath):
    db_dir = DP_DB_DIR
    if not os.path.exists(db_dir):
        rich_print("[yellow]No packages installed.[/yellow]")
        return False
    installed = sorted(os.listdir(db_dir))
    if not installed:
        rich_print("[yellow]No packages installed.[/yellow]")
        return False
    with open(filepath, "w") as f:
        for pkg in installed:
            f.write(pkg + "\n")
    rich_print(f"[green]Exported {len(installed)} packages to[/green] [bold]{filepath}[/bold]")
    return True


def import_installed(filepath):
    if not os.path.exists(filepath):
        rich_print(f"[red]File not found: {filepath}[/red]")
        return
    with open(filepath) as f:
        pkgs = [line.strip() for line in f if line.strip()]
    if not pkgs:
        rich_print("[yellow]No packages in list.[/yellow]")
        return
    total = len(pkgs)
    ok = 0
    failed = 0
    for i, pkg in enumerate(pkgs, 1):
        rich_print(f"[bold blue]({i}/{total})[/bold blue] Installing [green]{pkg}[/green]...")
        try:
            install_package(pkg)
            ok += 1
        except Exception as e:
            rich_print(f"  [red]failed: {e}[/red]")
            failed += 1
    rich_print(f"[bold green]Done:[/bold green] {ok} installed, {failed} failed.")


# ── verify-all ──────────────────────────────────────────────────────

def verify_all():
    db_dir = DP_DB_DIR
    if not os.path.exists(db_dir):
        rich_print("[yellow]No packages installed.[/yellow]")
        return
    installed = sorted(os.listdir(db_dir))
    if not installed:
        rich_print("[yellow]No packages installed.[/yellow]")
        return
    total_missing = 0
    total_packages = 0
    for pkg in installed:
        list_path = os.path.join(db_dir, pkg)
        if not os.path.exists(list_path):
            continue
        with open(list_path) as f:
            files = [l.strip() for l in f if l.strip()]
        missing = [f for f in files if not os.path.exists(f)]
        if missing:
            rich_print(f"[yellow]{pkg}:[/yellow] {len(missing)} missing file(s)")
            for m in missing:
                rich_print(f"  [dim]{m}[/dim]")
            total_missing += len(missing)
            total_packages += 1
    if total_missing == 0:
        rich_print(f"[green]All {len(installed)} packages intact.[/green]")
    else:
        rich_print(f"[yellow]{total_packages} packages with {total_missing} missing file(s).[/yellow]")
    return total_missing == 0


# ── Why (dependency chain) ──────────────────────────────────────────

def show_why(package_name):
    db_dir = DP_DB_DIR
    if not os.path.exists(db_dir):
        rich_print(f"[yellow]Package '{package_name}' is not installed.[/yellow]")
        return
    pkg_path = os.path.join(db_dir, package_name)
    if not os.path.exists(pkg_path):
        rich_print(f"[yellow]Package '{package_name}' is not installed.[/yellow]")
        return

    installed = sorted(os.listdir(db_dir))
    reverse_deps = {}
    for pkg in installed:
        list_path = os.path.join(db_dir, pkg)
        try:
            with open(list_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parent = os.path.dirname(line)
                    if parent == '/dpms-db':
                        continue
                    fname = os.path.basename(line)
                    if fname == package_name:
                        reverse_deps.setdefault(pkg, []).append(line)
                    name_only = line.rsplit('/', 1)[-1].rsplit('.', 1)[0]
                    if name_only == package_name:
                        if pkg not in reverse_deps:
                            reverse_deps.setdefault(pkg, [])
                        if line not in reverse_deps[pkg]:
                            reverse_deps[pkg].append(line)
        except Exception:
            pass

    from rich.tree import Tree
    from rich.console import Console
    con = Console()

    if reverse_deps:
        tree = Tree(f"[bold]{package_name}[/bold]")
        for parent, refs in sorted(reverse_deps.items()):
            branch = tree.add(f"[cyan]{parent}[/cyan]")
            for ref in refs[:3]:
                branch.add(f"[dim]{ref}[/dim]")
            if len(refs) > 3:
                branch.add(f"[dim]... +{len(refs) - 3} more[/dim]")
        rich_print(f"\n[bold]Why is '{package_name}' installed?[/bold]")
        con.print(tree)
    else:
        rich_print(f"[green]'{package_name}'[/green] is installed [bold]manually[/bold] (no reverse deps found).")
    return bool(reverse_deps)


# ── Hold / Unhold / List-held ───────────────────────────────────────

HOLD_FILE = os.path.join(DP_DB_DIR, ".held")

def _load_holds():
    if not os.path.exists(HOLD_FILE):
        return set()
    with open(HOLD_FILE) as f:
        return set(line.strip() for line in f if line.strip())

def _save_holds(holds):
    os.makedirs(os.path.dirname(HOLD_FILE), exist_ok=True)
    with open(HOLD_FILE, "w") as f:
        for pkg in sorted(holds):
            f.write(pkg + "\n")

def hold_package(name):
    holds = _load_holds()
    holds.add(name)
    _save_holds(holds)
    rich_print(f"[green]Held[/green] {name} [dim](will not be upgraded)[/dim]")

def unhold_package(name):
    holds = _load_holds()
    holds.discard(name)
    _save_holds(holds)
    rich_print(f"[green]Unheld[/green] {name}")

def list_held():
    holds = _load_holds()
    if not holds:
        rich_print("[yellow]No held packages.[/yellow]")
        return
    rich_print(f"[bold]Held packages ({len(holds)}):[/bold]")
    for pkg in sorted(holds):
        rich_print(f"  [cyan]{pkg}[/cyan]")


# ── Duplicates ──────────────────────────────────────────────────────

def find_duplicates():
    db_dir = DP_DB_DIR
    if not os.path.exists(db_dir):
        rich_print("[yellow]No packages installed.[/yellow]")
        return
    installed = sorted(os.listdir(db_dir))
    file_map = {}
    for pkg in installed:
        list_path = os.path.join(db_dir, pkg)
        try:
            with open(list_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        file_map.setdefault(line, []).append(pkg)
        except Exception:
            pass
    duplicates = {f: pkgs for f, pkgs in file_map.items() if len(pkgs) > 1}
    if not duplicates:
        rich_print("[green]No duplicate files found.[/green]")
        return
    from rich.table import Table
    from rich.console import Console
    con = Console()
    table = Table(title=f"Duplicate Files ({len(duplicates)})", border_style="yellow")
    table.add_column("File", style="bold")
    table.add_column("Packages")
    for f, pkgs in sorted(duplicates.items()):
        table.add_row(f, ", ".join(pkgs))
    con.print(table)


# ── Backup / Restore ────────────────────────────────────────────────

def backup_db(dest_dir):
    db_dir = DP_DB_DIR
    if not os.path.exists(db_dir):
        rich_print("[yellow]No package database to back up.[/yellow]")
        return False
    os.makedirs(dest_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"dpms_backup_{timestamp}.tar.xz"
    archive_path = os.path.join(dest_dir, archive_name)
    config_dir = os.path.expanduser("~/.config/dpms")
    with tarfile.open(archive_path, "w:xz") as tar:
        tar.add(db_dir, arcname="dpms_db")
        for extra in ["repo_list.json"]:
            extra_path = os.path.join(config_dir, extra)
            if os.path.exists(extra_path):
                tar.add(extra_path, arcname=f"config/{extra}")
    rich_print(f"[green]Backup saved:[/green] [bold]{archive_path}[/bold]")
    return True


def restore_db(archive_path):
    if not os.path.exists(archive_path):
        rich_print(f"[red]Backup not found: {archive_path}[/red]")
        return False
    db_dir = DP_DB_DIR
    old_dir = db_dir + ".old"
    if os.path.exists(old_dir):
        shutil.rmtree(old_dir)
    if os.path.exists(db_dir):
        os.rename(db_dir, old_dir)
        rich_print(f"[dim]Saved old db as {old_dir}[/dim]")
    try:
        dest_root = os.path.normpath(os.path.dirname(db_dir))
        with tarfile.open(archive_path, "r:xz") as tar:
            for member in tar.getmembers():
                member_path = os.path.normpath(member.name)
                if member_path.startswith(("..", "/")):
                    raise ArchiveError(f"Path traversal blocked: {member.name}")
                dest = os.path.join(dest_root, member_path)
                if not dest.startswith(dest_root):
                    raise ArchiveError(f"Path traversal blocked: {member.name}")
            tar.extractall(path=dest_root)
        if os.path.exists(os.path.join(dest_root, "dpms_db")):
            if os.path.exists(db_dir):
                shutil.rmtree(db_dir)
            os.rename(os.path.join(os.path.dirname(db_dir), "dpms_db"), db_dir)
        rich_print(f"[green]Database restored from:[/green] [bold]{archive_path}[/bold]")
        return True
    except Exception as e:
        if os.path.exists(old_dir) and not os.path.exists(db_dir):
            os.rename(old_dir, db_dir)
        rich_print(f"[red]Restore failed: {e}[/red]")
        return False


# ── Compare versions ────────────────────────────────────────────────

def compare_versions(v1, v2):
    p1 = _parse_version(v1)
    p2 = _parse_version(v2)
    if p1 == p2:
        rich_print(f"[yellow]{v1} == {v2}[/yellow] (equal)")
        return 0
    elif p1 < p2:
        rich_print(f"[green]{v1} < {v2}[/green] ({v1} is older)")
        return -1
    else:
        rich_print(f"[green]{v1} > {v2}[/green] ({v1} is newer)")
        return 1


# ── Changelog ───────────────────────────────────────────────────────

def show_changelog(package_name):
    possible = [
        os.path.join(DP_DB_DIR, f"{package_name}.changelog"),
        os.path.join(REPOSITORY_DIR, f"{package_name}.changelog"),
    ]
    for path in possible:
        if os.path.exists(path):
            with open(path) as f:
                rich_print(f"[bold]Changelog for {package_name}:[/bold]")
                rich_print(f.read())
            return
    rich_print(f"[yellow]No changelog found for '{package_name}'.[/yellow]")


# ── Purge package ────────────────────────────────────────────────────

def purge_package(package_name, verbose=False):
    if not confirm_delete(f"purge '{package_name}' (removes all config and data)"):
        return False
    rich_print(f"[bold red]Purging[/bold red] {package_name}...")
    remove_package(package_name, verbose=verbose)
    config_paths = [
        os.path.join(os.path.expanduser("~/.config/dpms"), package_name),
        os.path.join(os.path.expanduser("~/.local/share/dpms"), package_name),
        os.path.join(DP_DB_DIR, f"{package_name}.conf"),
        os.path.join(DP_DB_DIR, f"{package_name}.changelog"),
    ]
    removed = 0
    for path in config_paths:
        if os.path.isfile(path):
            os.remove(path)
            removed += 1
            if verbose:
                rich_print(f"  [dim]removed {path}[/dim]")
        elif os.path.isdir(path):
            shutil.rmtree(path)
            removed += 1
            if verbose:
                rich_print(f"  [dim]removed {path}/[/dim]")
    rich_print(f"[bold green]Purge complete:[/bold green] {package_name} removed ({removed} config files)")


# ── Package size ─────────────────────────────────────────────────────

def show_package_size(package_name):
    list_path = os.path.join(DP_DB_DIR, package_name)
    if not os.path.exists(list_path):
        rich_print(f"[yellow]Package '{package_name}' is not installed.[/yellow]")
        return
    total_bytes = 0
    file_count = 0
    try:
        with open(list_path) as f:
            for line in f:
                fp = line.strip()
                if fp and os.path.exists(fp):
                    total_bytes += os.path.getsize(fp)
                    file_count += 1
    except Exception as e:
        rich_print(f"[red]Error reading file list: {e}[/red]")
        return
    from rich.table import Table
    from rich.console import Console
    con = Console()
    table = Table(title=f"Size: {package_name}")
    table.add_column("Metric", style="bold green")
    table.add_column("Value")
    table.add_row("Files", str(file_count))
    if total_bytes >= 1073741824:
        table.add_row("Size", f"{total_bytes / 1073741824:.2f} GiB")
    elif total_bytes >= 1048576:
        table.add_row("Size", f"{total_bytes / 1048576:.2f} MiB")
    elif total_bytes >= 1024:
        table.add_row("Size", f"{total_bytes / 1024:.2f} KiB")
    else:
        table.add_row("Size", f"{total_bytes} B")
    con.print(table)


# ── List files by type ───────────────────────────────────────────────

def list_files_by_type(package_name, extension):
    list_path = os.path.join(DP_DB_DIR, package_name)
    if not os.path.exists(list_path):
        rich_print(f"[yellow]Package '{package_name}' is not installed.[/yellow]")
        return
    ext = extension if extension.startswith(".") else f".{extension}"
    matched = []
    try:
        with open(list_path) as f:
            for line in f:
                fp = line.strip()
                if fp and fp.endswith(ext):
                    matched.append(fp)
    except Exception as e:
        rich_print(f"[red]Error: {e}[/red]")
        return
    if not matched:
        rich_print(f"[yellow]No *{ext} files in '{package_name}'.[/yellow]")
        return
    from rich.table import Table
    from rich.console import Console
    con = Console()
    table = Table(title=f"*{ext} files in '{package_name}' ({len(matched)})")
    table.add_column("#", style="dim")
    table.add_column("Path")
    for i, fp in enumerate(matched, 1):
        exists = os.path.exists(fp)
        icon = "[green]\u2713[/green]" if exists else "[red]\u2717[/red]"
        table.add_row(str(i), f"{icon} {fp}")
    con.print(table)


# ── List recent packages ─────────────────────────────────────────────

def list_recent(n=10):
    db_dir = DP_DB_DIR
    if not os.path.exists(db_dir):
        rich_print("[yellow]No packages installed.[/yellow]")
        return
    installed = os.listdir(db_dir)
    if not installed:
        rich_print("[yellow]No packages installed.[/yellow]")
        return
    with_times = []
    for pkg in installed:
        pkg_path = os.path.join(db_dir, pkg)
        try:
            mtime = os.path.getmtime(pkg_path)
            with_times.append((mtime, pkg))
        except OSError:
            continue
    with_times.sort(reverse=True)
    recent = with_times[:n]
    from rich.table import Table
    from rich.console import Console
    from datetime import datetime
    con = Console()
    table = Table(title=f"Recent packages (last {len(recent)})")
    table.add_column("Package", style="bold green")
    table.add_column("Installed")
    for mtime, pkg in recent:
        dt = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        table.add_row(pkg, dt)
    con.print(table)
