#!/usr/bin/env python3
"""dpms_logs — handle dlr.log, <name>.log, and nft.log files"""

import hashlib
import os
import subprocess
import sys
from pathlib import Path


def find_git_repo():
    current = Path.cwd().resolve()
    for parent in [current] + list(current.parents):
        if (parent / ".git").is_dir():
            os.chdir(parent)
            return parent
    return None


def cmd_dlr_verify():
    repo_root = find_git_repo()
    if repo_root is None:
        print("error: must be run from a git repo", file=sys.stderr)
        return False

    dlr = repo_root / "dlr.log"
    if not dlr.exists():
        print("error: dlr.log not found in repo root", file=sys.stderr)
        return False

    errors = 0
    with open(dlr) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            algo = parts[0].lower()
            expected_hash = parts[1]
            filepath = repo_root / " ".join(parts[2:])

            if algo not in ("sha256", "sha1", "sha512", "md5"):
                continue
            if not filepath.exists():
                print(f"MISSING  {filepath.relative_to(repo_root)}", file=sys.stderr)
                errors += 1
                continue

            h = hashlib.new(algo)
            with open(filepath, "rb") as fh:
                h.update(fh.read())
            computed = h.hexdigest()

            if computed != expected_hash:
                rel = filepath.relative_to(repo_root)
                print(f"FAIL     {rel}  ({algo})", file=sys.stderr)
                errors += 1

    if errors:
        print(f"{errors} verification error(s)", file=sys.stderr)
        return False

    print("dlr.log verification passed")
    return True


def cmd_list_nft():
    repo_root = find_git_repo()
    if repo_root is None:
        print("error: must be run from a git repo", file=sys.stderr)
        return False

    found = []
    for entry in sorted(repo_root.iterdir()):
        if entry.is_dir() and (entry / "nft.log").exists():
            found.append(entry.name)

    if not found:
        print("no nft.log markers found")
        return True

    print("excluded directories (nft.log):")
    for name in found:
        print(f"  {name}")
    return True


def main():
    if len(sys.argv) < 2:
        print("usage: dpms-logs <dlr-verify|list-nft>", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "dlr-verify":
        ok = cmd_dlr_verify()
    elif cmd == "list-nft":
        ok = cmd_list_nft()
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
