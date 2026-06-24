#!/usr/bin/env python3
"""portcommit - format & commit changes to local ports"""

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


def port_commit():
    repo_root = find_git_repo()
    if repo_root is None:
        print("error: must be run from a git repo", file=sys.stderr)
        return False

    for dir_entry in sorted(Path.cwd().iterdir()):
        if not dir_entry.is_dir():
            continue

        if (dir_entry / "nft.log").exists():
            continue

        log_file = dir_entry / f"{dir_entry.name}.log"
        if not log_file.exists():
            continue

        try:
            result = subprocess.run(
                ["bash", "-c", f"source {log_file} >/dev/null 2>&1 && echo \"$name $version $release\""],
                capture_output=True, text=True, check=True,
            )
            output = result.stdout.strip()
            if not output:
                continue
            parts = output.split()
            if len(parts) < 3:
                continue
            name, version, release = parts[0], parts[1], parts[2]
        except subprocess.CalledProcessError:
            continue

        local_version = f"{version}-{release}"

        tracked = bool(subprocess.run(
            ["git", "ls-files", str(log_file)],
            capture_output=True, text=True, check=False,
        ).stdout.strip())

        subprocess.run(["git", "add", str(dir_entry.name)], check=False)

        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--", str(dir_entry.name)],
            capture_output=True, text=True, check=False,
        ).stdout.strip()

        if not staged:
            continue

        if tracked:
            subprocess.run(["git", "commit", "-m", f"{name} : {local_version}"], capture_output=True, check=False)
        else:
            subprocess.run(["git", "commit", "-m", f"add {name}"], capture_output=True, check=False)

    return True


def main():
    if not port_commit():
        sys.exit(1)


if __name__ == "__main__":
    main()
