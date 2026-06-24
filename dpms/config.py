import os
import platform
import shutil
import sys
from rich import print as rprint

SYSTEM = platform.system().lower()
MACHINE = platform.machine().lower()


def detect_arch():
    m = MACHINE
    if m in ('amd64', 'x86_64', 'i686', 'i386'):
        return 'x86_64'
    if m in ('aarch64', 'arm64'):
        return 'aarch64'
    if m.startswith('armv'):
        return 'armv7'
    return m or 'x86_64'


DPMS_ARCH = detect_arch()
IS_MACOS = SYSTEM == 'darwin'
IS_LINUX = SYSTEM == 'linux'
IS_WINDOWS = SYSTEM == 'windows'


def _find_escalator():
    for cmd in ('sudo', 'doas'):
        if shutil.which(cmd):
            return cmd
    return None


PRIV_ESCALATOR = _find_escalator()
IS_ROOT = os.geteuid() == 0 if hasattr(os, 'geteuid') else False

NEEDS_ROOT_OPS = ('install', 'uninstall', 'reset', 'sync')


def needs_privileges(op_name):
    if IS_ROOT or IS_WINDOWS:
        return False
    if op_name not in NEEDS_ROOT_OPS:
        return False
    if INSTALL_ROOT_DIR == '/':
        return True
    for d in (INSTALL_ROOT_DIR, DP_DB_DIR):
        if os.path.exists(d) and not os.access(d, os.W_OK):
            return True
    return False


def reexec_with_privileges():
    escalator = PRIV_ESCALATOR
    if not escalator:
        return False
    cmd = [escalator, sys.executable, sys.argv[0]] + sys.argv[1:]
    try:
        os.execvp(escalator, cmd)
    except FileNotFoundError:
        rprint(f"[red]Privilege escalator '{escalator}' not found.[/red]")
        sys.exit(1)
    return True  # never reached


DPMS_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

REPOSITORY_DIR = os.path.join(DPMS_BASE_DIR, 'packages')

INSTALL_ROOT_DIR = os.environ.get('DPMS_ROOT', '/')

DP_DB_DIR = os.path.join(INSTALL_ROOT_DIR, 'var', 'lib', 'dp', 'installed')

DPMS_PASSWORD_FILE = os.path.join(DPMS_BASE_DIR, '.dpms_password')


def ensure_dirs():
    try:
        os.makedirs(DP_DB_DIR, exist_ok=True)
    except PermissionError:
        pass
    try:
        os.makedirs(REPOSITORY_DIR, exist_ok=True)
    except PermissionError:
        pass
