import os
import shutil
import subprocess
import hashlib
import tarfile
from rich.console import Console
from rich.table import Table
from rich import print as rich_print

console = Console()


def show_version(context="DPMS-GET"):
    from . import __version__
    rich_print(f"[bold cyan]{context} version {__version__}[/bold cyan]")


def show_package_info(package_name, verbose=False):
    from .dpms_core import load_repo_list

    repo = load_repo_list()
    if package_name in repo:
        info = repo[package_name]
        table = Table(title=f"Package: {package_name}")
        table.add_column("Field", style="bold green")
        table.add_column("Value")
        for key, val in info.items():
            table.add_row(key.capitalize(), str(val))
        console.print(table)
    else:
        rich_print(f"[yellow]Package '{package_name}' not found in repositories.[/yellow]")


# ── Build profiles (compiler flags) ────────────────────────────────

def set_build_profile(profile='standard'):
    nproc = os.cpu_count() or 2
    profiles = {
        'lite':       ('-j1',                                '-Os -pipe',             '-Os -pipe'),
        'performance': (f'-j{nproc}', '-O3 -march=native -pipe', '-O3 -march=native -pipe'),
    }
    if profile in profiles:
        mf, cf, cxf = profiles[profile]
    elif profile == 'custom':
        mf = os.environ.get('DPMS_MAKEFLAGS', '-j2')
        cf = os.environ.get('DPMS_CFLAGS',   '-O2 -march=native -pipe')
        cxf = os.environ.get('DPMS_CXXFLAGS', '-O3 -pipe')
    else:
        mf = f'-j{max(1, nproc // 2)}'
        cf = '-O2 -pipe'
        cxf = '-O2 -pipe'
    os.environ['MAKEFLAGS'] = mf
    os.environ['CFLAGS']    = cf
    os.environ['CXXFLAGS']  = cxf
    rich_print(f"[dim]Build profile: {profile} (MAKEFLAGS={mf})[/dim]")


# ── SHA256 verification ────────────────────────────────────────────

def verify_checksum(file_path, expected_sha256):
    sha256 = hashlib.sha256()
    try:
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                sha256.update(chunk)
        actual = sha256.hexdigest()
        return actual == expected_sha256
    except (IOError, OSError) as e:
        rich_print(f"[red]Checksum verification failed: {e}[/red]")
        return False


def verify_checksum_from_file(file_path, sha_file):
    """Verify file against a USHA256.list style file."""
    pkg_name = os.path.basename(file_path)
    if not os.path.exists(sha_file):
        rich_print(f"[red]SHA256 list not found: {sha_file}[/red]")
        return False
    with open(sha_file) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2 and parts[1] == pkg_name:
                return verify_checksum(file_path, parts[0])
    rich_print(f"[red]No SHA256 entry found for {pkg_name}[/red]")
    return False


# ── Source-based build (from UBUILD.sh archives) ───────────────────

def build_from_source(pkg_name, repo_urls=None):
    """Download a source archive from repos, verify, build and install it.

    Expects a ``.tar.gz`` archive containing ``UBUILD.sh`` (and
    optionally a ``UPATCHES/`` directory of patches).
    """
    from .dpms_core import load_repo_list

    if repo_urls is None:
        repo_urls = []
        for name, info in load_repo_list().items():
            url = info.get('url', '')
            if url and not url.endswith('.git'):
                repo_urls.append(url)

    if not shutil.which('wget'):
        rich_print("[red]wget is required for source builds but not found.[/red]")
        return False

    tmp = os.environ.get('DPMS_TMP_DIR', '/tmp/dpms-build')
    os.makedirs(tmp, exist_ok=True)
    target = os.path.join(tmp, f"{pkg_name}.tar.gz")

    found = False
    sha_url = None
    for url in repo_urls:
        pkg_url = f"{url}/{pkg_name}.tar.gz"
        rich_print(f"[cyan]Checking {pkg_url} ...[/cyan]")
        probe = subprocess.run(['wget', '-q', '--spider', pkg_url],
                               capture_output=True)
        if probe.returncode == 0:
            rich_print(f"[green]Found {pkg_name} in {url}[/green]")
            try:
                subprocess.run(['wget', '-q', '--show-progress', '-O', target, pkg_url],
                               check=True, capture_output=True)
            except subprocess.CalledProcessError:
                rich_print("[red]Failed to download package.[/red]")
                return False
            sha_url = f"{url}/USHA256.list"
            found = True
            break

    if not found:
        rich_print(f"[red]Package '{pkg_name}' not found in any repository![/red]")
        return False

    if sha_url:
        sha_file = os.path.join(tmp, 'USHA256.list')
        try:
            subprocess.run(['wget', '-q', sha_url, '-O', sha_file], check=True,
                           capture_output=True)
            if not verify_checksum_from_file(target, sha_file):
                rich_print("[red]SHA256 mismatch! Aborting.[/red]")
                os.remove(target)
                return False
        except subprocess.CalledProcessError:
            rich_print("[yellow]Could not fetch checksum list — skipping verification.[/yellow]")

    src_dir = os.path.join(tmp, pkg_name)
    if os.path.exists(src_dir):
        shutil.rmtree(src_dir)

    with tarfile.open(target, 'r:gz') as tar:
        tar.extractall(path=tmp)

    src_dir = os.path.join(tmp, pkg_name)
    if not os.path.isdir(src_dir):
        rich_print(f"[red]Extracted directory not found: {src_dir}[/red]")
        return False

    patch_dir = os.path.join(src_dir, 'UPATCHES')
    if os.path.isdir(patch_dir):
        rich_print("[yellow]Applying patches...[/yellow]")
        for patch in sorted(os.listdir(patch_dir)):
            if patch.endswith('.patch'):
                pp = os.path.join(patch_dir, patch)
                subprocess.run(['patch', '-p1', '-N', '--batch', '-i', pp],
                               capture_output=True)
        rich_print("[green]Patches applied.[/green]")

    build_script = os.path.join(src_dir, 'UBUILD.sh')
    if not os.path.exists(build_script):
        rich_print(f"[red]UBUILD.sh not found in {src_dir}![/red]")
        return False
    os.chmod(build_script, 0o755)

    pkg_opt = os.path.join(os.environ.get('DPMS_OPT_DIR', '/opt'), pkg_name)
    pkg_bin = os.environ.get('DPMS_BIN_DIR', '/usr/local/bin')
    os.makedirs(pkg_opt, exist_ok=True)

    orig = os.getcwd()
    try:
        os.chdir(src_dir)
        set_build_profile(os.environ.get('DPMS_BUILD_PROFILE', 'standard'))
        rich_print(f"[cyan]Building {pkg_name}...[/cyan]")
        r = subprocess.run([build_script, pkg_opt, pkg_bin, pkg_name])
        if r.returncode != 0:
            rich_print("[red]Build failed![/red]")
            return False
    finally:
        os.chdir(orig)

    shutil.rmtree(src_dir, ignore_errors=True)
    if os.path.exists(target):
        os.remove(target)
    rich_print(f"[green]{pkg_name} built and installed successfully![/green]")
    return True
