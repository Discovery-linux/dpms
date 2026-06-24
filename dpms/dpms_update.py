import errno
import os
import re
import shutil
import stat

from . import config

DP_DB_DIR = config.DP_DB_DIR
INSTALL_ROOT_DIR = config.INSTALL_ROOT_DIR


def update_dbentry(update_cmd, file_list_content):
    if update_cmd[0] == 'move':
        old_name = update_cmd[1]
        new_name = update_cmd[2]
        if old_name == new_name:
            return file_list_content

        lines = file_list_content.splitlines(True)
        modified = False
        for i, line in enumerate(lines):
            stripped = line.rstrip('\n')
            parts = stripped.split('/')
            changed = False
            for j, part in enumerate(parts):
                if part == old_name:
                    parts[j] = new_name
                    changed = True
                elif part.startswith(old_name + '-') or part.startswith(old_name + '.'):
                    parts[j] = new_name + part[len(old_name):]
                    changed = True
            if changed:
                lines[i] = '/'.join(parts) + '\n'
                modified = True

        if modified:
            return ''.join(lines)

    return file_list_content


def update_dbentries(update_iter, dbdata):
    updated = {}
    for key, content in dbdata.items():
        if key in ('CONTENTS', 'environment.bz2'):
            continue
        original = content
        for cmd in update_iter:
            content = update_dbentry(cmd, content)
        if content != original:
            updated[key] = content
    return updated


def parse_updates(text):
    commands = []
    errors = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        if parts[0] == 'move':
            if len(parts) != 3:
                errors.append(f"Invalid move command: {line!r}")
                continue
            commands.append(parts)
        else:
            errors.append(f"Unknown update type: {parts[0]!r}")
    return commands, errors


def grab_updates(upd_path, prev_mtimes=None):
    if prev_mtimes is None:
        prev_mtimes = {}

    try:
        entries = sorted(os.listdir(upd_path))
    except OSError as e:
        if e.errno == errno.ENOENT:
            return []
        raise

    updates = []
    for name in entries:
        if name.startswith('.'):
            continue
        fpath = os.path.join(upd_path, name)
        try:
            st = os.stat(fpath)
        except OSError:
            continue
        if not stat.S_ISREG(st.st_mode):
            continue
        prev = prev_mtimes.get(fpath, -1)
        if int(prev) != int(st.st_mtime):
            with open(fpath) as f:
                content = f.read()
            updates.append((fpath, st, content))
    return updates


# HACK: moving files on disk is risky, should probably just symlink
def apply_move(cmd):
    old_name, new_name = cmd[1], cmd[2]
    old_path = os.path.join(DP_DB_DIR, old_name)
    new_path = os.path.join(DP_DB_DIR, new_name)

    if not os.path.exists(old_path):
        return 0

    with open(old_path) as f:
        old_content = f.read()

    new_content = update_dbentry(cmd, old_content)
    changed = new_content != old_content

    if changed:
        old_files = [l.rstrip('\n') for l in old_content.splitlines() if l.strip()]
        new_files = [l.rstrip('\n') for l in new_content.splitlines() if l.strip()]

        for old_f, new_f in zip(old_files, new_files):
            if old_f != new_f and os.path.exists(old_f):
                new_dir = os.path.dirname(new_f)
                os.makedirs(new_dir, exist_ok=True)
                shutil.move(old_f, new_f)

        dirs = set()
        for f in old_files:
            d = os.path.dirname(f)
            while d and d != '/':
                dirs.add(d)
                d = os.path.dirname(d)
        for d in sorted(dirs, key=len, reverse=True):
            try:
                if os.path.isdir(d) and not os.listdir(d):
                    os.rmdir(d)
            except OSError:
                pass

    os.makedirs(DP_DB_DIR, exist_ok=True)
    with open(new_path, 'w') as f:
        f.write(new_content)

    os.remove(old_path)

    return 1 if changed else 0


def apply_updates(upd_path):
    updates = grab_updates(upd_path)
    total = 0
    for fpath, st, content in updates:
        commands, errors = parse_updates(content)
        if errors:
            continue
        for cmd in commands:
            if cmd[0] == 'move':
                total += apply_move(cmd)
    return total
