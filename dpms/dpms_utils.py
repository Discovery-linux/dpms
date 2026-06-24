import argparse
import errno
import functools
import getpass
import itertools
import locale
import logging
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from rich.console import Console
from rich.text import Text

from .dpms_pycomp import basestring, filterfalse

logger = logging.getLogger("dpms")

if __package__ is None:
    from dpms_core import (
        make_tar, download_file,
        DPMSCoreError, InvalidSourceError,
        UnsupportedCompressionError, SubprocessError, NetworkError
    )
else:
    from .dpms_core import (
        make_tar, download_file,
        DPMSCoreError, InvalidSourceError,
        UnsupportedCompressionError, SubprocessError, NetworkError
    )

console = Console()

from . import config
DPMS_PASSWORD_FILE = getattr(config, 'DPMS_PASSWORD_FILE',
    os.path.join(os.path.expanduser('~'), '.dpms', 'password'))


def _get_stored_password():
    if os.path.exists(DPMS_PASSWORD_FILE):
        with open(DPMS_PASSWORD_FILE, 'r') as f:
            return f.read().strip()
    return None


def authenticate_user():
    stored = _get_stored_password()
    if not stored:
        console.print("[yellow]No password set. Please use set_password() first.[/yellow]")
        return False
    attempt = getpass.getpass("Enter DPMS password: ")
    if attempt == stored:
        return True
    console.print("[red]Incorrect password![/red]")
    return False


def set_password():
    pw = getpass.getpass("Set a new DPMS password: ")
    confirm = getpass.getpass("Confirm password: ")
    if pw != confirm:
        console.print("[red]Passwords do not match![/red]")
        return
    os.makedirs(os.path.dirname(DPMS_PASSWORD_FILE), exist_ok=True)
    with open(DPMS_PASSWORD_FILE, 'w') as f:
        f.write(pw)
    console.print("[green]Password set successfully![/green]")


def cli_compress(source_path, output_filename, compression_type='gz', verbose=False):
    try:
        make_tar(source_path, output_filename, compression_type, verbose=verbose)
        console.print(f"[green]Compression successful:[/green] {output_filename}")
    except (InvalidSourceError, UnsupportedCompressionError, SubprocessError, DPMSCoreError) as e:
        console.print(f"[red]Error:[/red] {e}")
        if hasattr(e, 'stderr') and e.stderr:
            console.print(f"[yellow]Stderr:[/yellow] {e.stderr}")
    except Exception as e:
        console.print(f"[red]Unexpected error:[/red] {e}")


def cli_download(url, output_path, verbose=False):
    try:
        download_file(url, output_path, verbose=verbose)
        console.print(f"[green]Download completed:[/green] {output_path}")
    except (NetworkError, DPMSCoreError, SubprocessError) as e:
        console.print(f"[red]Error:[/red] {e}")
    except Exception as e:
        console.print(f"[red]Unexpected error:[/red] {e}")


def launch_gui():
    try:
        if __package__ is None:
            from dpms_gui import main as run_gui
        else:
            from .dpms_gui import main as run_gui
        run_gui()
    except ImportError:
        console.print("[red]GUI not available. Install PyQt5: pip install PyQt5[/red]")
    except Exception as e:
        console.print(f"[red]Failed to launch GUI:[/red] {e}")


def reset_config():
    dpms_dir = os.path.join(os.path.expanduser('~'), '.dpms')
    if os.path.exists(dpms_dir):
        try:
            import shutil
            shutil.rmtree(dpms_dir)
            console.print(f"[green]DPMS configuration reset successfully.[/green]")
        except Exception as e:
            console.print(f"[red]Failed to reset DPMS config:[/red] {e}")
    else:
        console.print("[yellow]DPMS configuration folder not found.[/yellow]")


def am_i_root():
    return os.geteuid() == 0


def ensure_dir(dname):
    try:
        os.makedirs(dname, mode=0o755)
    except OSError as e:
        if e.errno != errno.EEXIST or not os.path.isdir(dname):
            raise


def clear_dir(path):
    for entry in os.listdir(path):
        contained_path = os.path.join(path, entry)
        rm_rf(contained_path)


def rm_rf(path):
    try:
        shutil.rmtree(path)
    except OSError:
        pass


def touch(path, no_create=False):
    if no_create or os.access(path, os.F_OK):
        return os.utime(path, None)
    with open(path, 'a'):
        pass


def empty(iterable):
    try:
        l = len(iterable)
    except TypeError:
        l = len(list(iterable))
    return l == 0


def first(iterable):
    it = iter(iterable)
    try:
        return next(it)
    except StopIteration:
        return None


def first_not_none(iterable):
    it = iter(iterable)
    try:
        return next(item for item in it if item is not None)
    except StopIteration:
        return None


def file_age(fn):
    return time.time() - file_timestamp(fn)


def file_timestamp(fn):
    return os.stat(fn).st_mtime


def get_effective_login():
    try:
        return pwd.getpwuid(os.geteuid())[0]
    except KeyError:
        return "UID: %s" % os.geteuid()


def is_glob_pattern(pattern):
    if isinstance(pattern, basestring):
        pattern = [pattern]
    return (isinstance(pattern, list) and any(set(p) & set("*[?") for p in pattern))


def is_string_type(obj):
    return isinstance(obj, basestring)


def strip_prefix(s, prefix):
    if s.startswith(prefix):
        return s[len(prefix):]
    return None


def split_path(path):
    result = []
    head = path
    while True:
        head, tail = os.path.split(head)
        if not tail:
            if head or not result:
                result.insert(0, head)
            break
        result.insert(0, tail)
    return result


def normalize_time(timestamp):
    return time.strftime("%c", time.localtime(timestamp))


def rtrim(s, r):
    if s.endswith(r):
        s = s[:-len(r)]
    return s


def group_by_filter(fn, iterable):
    def splitter(acc, item):
        acc[not bool(fn(item))].append(item)
        return acc
    return functools.reduce(splitter, iterable, ([], []))


def partition(pred, iterable):
    t1, t2 = itertools.tee(iterable)
    return filterfalse(pred, t1), filter(pred, t2)


def insert_if(item, iterable, condition):
    for original_item in iterable:
        if condition(original_item):
            yield item
        yield original_item


def split_by(iterable, condition):
    separator = object()
    def next_subsequence(it):
        return tuple(itertools.takewhile(lambda e: e != separator, it))
    marked = insert_if(separator, iterable, condition)
    yield next_subsequence(marked)
    while True:
        subsequence = next_subsequence(marked)
        if not subsequence:
            break
        yield subsequence


def mapall(fn, *seq):
    return list(map(fn, *seq))


def lazyattr(attrname):
    def get_decorated(fn):
        def cached_getter(obj):
            try:
                return getattr(obj, attrname)
            except AttributeError:
                val = fn(obj)
                setattr(obj, attrname, val)
                return val
        return cached_getter
    return get_decorated


class Bunch(dict):
    def __init__(self, *args, **kwds):
        super(Bunch, self).__init__(*args, **kwds)
        self.__dict__ = self

    def __hash__(self):
        return id(self)


class MultiCallList(list):
    def __init__(self, iterable):
        super(MultiCallList, self).__init__()
        self.extend(iterable)

    def __getattr__(self, what):
        def fn(*args, **kwargs):
            def call_what(v):
                method = getattr(v, what)
                return method(*args, **kwargs)
            return list(map(call_what, self))
        return fn

    def __setattr__(self, what, val):
        def setter(item):
            setattr(item, what, val)
        return list(map(setter, self))


class tmpdir(object):
    def __init__(self):
        self.path = tempfile.mkdtemp(prefix='dpms-')

    def __enter__(self):
        return self.path

    def __exit__(self, exc_type, exc_value, traceback):
        rm_rf(self.path)


def main():
    parser = argparse.ArgumentParser(description="DPMS Utilities CLI")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    compress_parser = subparsers.add_parser("convert", help="Compress a folder into tar.gz or tar.xz")
    compress_parser.add_argument("source_path", help="Path to folder")
    compress_parser.add_argument("output_filename", help="Output archive filename")
    compress_parser.add_argument("-c", "--compression_type", choices=["gz", "xz"], default="gz")

    download_parser = subparsers.add_parser("download", help="Download file from URL")
    download_parser.add_argument("url", help="File URL")
    download_parser.add_argument("output_path", help="Save location")

    subparsers.add_parser("gui", help="Launch GUI")

    subparsers.add_parser("set-password", help="Set DPMS password")

    subparsers.add_parser("reset", help="Reset DPMS configuration")

    if len(sys.argv) < 2:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()

    if args.command == "convert":
        cli_compress(args.source_path, args.output_filename, args.compression_type, verbose=args.verbose)
    elif args.command == "download":
        cli_download(args.url, args.output_path, verbose=args.verbose)
    elif args.command == "gui":
        launch_gui()
    elif args.command == "set-password":
        set_password()
    elif args.command == "reset":
        reset_config()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
