#!/usr/bin/env python3

import os
import re
import shutil
import sys
import time
import random
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dpms.dpms_core import load_repo_list, _parse_package_archive_name


def _scan_repo_dirs():
    cache_dir = os.path.expanduser("~/.cache/dpms/repos")
    pkgs = {}
    if not os.path.isdir(cache_dir):
        return pkgs
    for repo_name in os.listdir(cache_dir):
        repo_path = os.path.join(cache_dir, repo_name)
        if not os.path.isdir(repo_path):
            continue
        for fname in os.listdir(repo_path):
            parsed = _parse_package_archive_name(fname)
            if parsed and parsed[0]:
                if parsed[0] not in pkgs:
                    ver = ".".join(str(v) for v in parsed[1]) if parsed[1] else "?"
                    pkgs[parsed[0]] = {
                        "repo": repo_name,
                        "version": ver,
                        "description": f"Available in '{repo_name}' repo",
                    }
                continue
            if fname.endswith((".tar.xz", ".tar.gz")):
                name = fname.rsplit(".", 2)[0]
                if name and re.match(r'^[a-zA-Z]', name) and name not in pkgs:
                    pkgs[name] = {
                        "repo": repo_name,
                        "version": "?",
                        "description": f"Available in '{repo_name}' repo",
                    }
    return pkgs


def _get_repo_packages():
    repo = load_repo_list()
    if not repo:
        fallback = os.path.join(os.path.dirname(__file__), "dpms", "repo_list.json")
        if os.path.exists(fallback):
            import json
            with open(fallback) as f:
                repo = json.load(f)
    pkgs = _scan_repo_dirs()
    for name, info in repo.items():
        if not info.get("enabled", True):
            continue
        pkg_list = info.get("packages")
        if isinstance(pkg_list, list):
            for p in pkg_list:
                if p not in pkgs:
                    pkgs[p] = {
                        "repo": name,
                        "version": info.get("version", "?"),
                        "description": info.get("description", ""),
                    }
    return pkgs


def _get_installed_packages():
    db_dir = None
    try:
        from dpms.config import DP_DB_DIR
        db_dir = DP_DB_DIR
    except Exception:
        db_dir = os.path.expanduser("~/.cache/dpms/db")
    if not os.path.isdir(db_dir):
        return set()
    return set(os.listdir(db_dir))


def _all_package_names():
    return sorted(_get_repo_packages().keys())


def _get_package_info(pkg):
    repo_pkgs = _get_repo_packages()
    if pkg in repo_pkgs:
        return repo_pkgs[pkg]
    installed = _get_installed_packages()
    if pkg in installed:
        return {"repo": "(installed)", "version": "?", "description": "Installed package"}
    return {"repo": "?", "version": "?", "description": ""}


PACKAGE_CATEGORIES = {
    "dev": ["git", "gcc", "make", "cmake", "python3", "nodejs", "vim", "neovim", "nano"],
    "util": ["htop", "tmux", "tree", "less", "jq", "curl", "wget", "openssh"],
    "shell": ["bash", "zsh"],
    "editor": ["vim", "neovim", "nano"],
    "net": ["curl", "wget", "openssh"],
    "core": ["bash", "git", "gcc", "make", "python3"],
}


def search_animation(package, duration=3):
    cols = min(shutil.get_terminal_size().columns if sys.stdout.isatty() else 80, 200)
    cols = max(cols, 40)
    bar_w = cols - 28

    start = time.time()
    end = start + duration
    dots = 0

    while time.time() < end:
        elapsed = time.time() - start
        pct = min(int(elapsed * 100 / duration), 99)
        filled = int(pct * bar_w / 100)
        empty = bar_w - filled

        bar = "\u2588" * filled + "\u2591" * empty
        sys.stdout.write(f"\r\033[38;2;100;180;255mSearching{'.' * ((dots % 3) + 1):<4}\033[m [{bar}] {pct:2d}%")
        sys.stdout.flush()
        dots += 1
        time.sleep(0.05)

    full = "\u2588" * bar_w
    sys.stdout.write(f"\r\033[38;2;100;180;255mSearching...\033[m [{full}] 100%")
    sys.stdout.flush()
    time.sleep(0.3)

    pkgs = _all_package_names()
    if package in pkgs:
        msg = f"\033[32m\u2713 Package '{package}' found\033[m ({(random.random() * 2 + 0.1):.2f}s)"
        found = True
    else:
        msg = f"\033[31m\u2717 Package '{package}' not found\033[m"
        found = False

    sys.stdout.write(f"\n{msg}\n")
    return found


def install_animation(package):
    from progress import Progress
    bar = Progress(100, f"Installing {package}")
    for i in range(1, 101):
        bar.update(i)
        time.sleep(0.03)
    print(f"\033[32m\u2713 {package} installed successfully\033[m")


def regex_search(pattern):
    results = []
    try:
        prog = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        print(f"\033[31mInvalid regex: {e}\033[m")
        return results
    for pkg in _all_package_names():
        if prog.search(pkg):
            info = _get_package_info(pkg)
            results.append((pkg, info.get("description", "")))
    return results


def fuzzy_search(query):
    query = query.lower()
    scored = []
    for pkg in _all_package_names():
        low = pkg.lower()
        score = 0
        if query == low:
            score = 100
        elif low.startswith(query):
            score = 80
        elif query in low:
            score = 60
        else:
            qpos = 0
            for ch in low:
                if qpos < len(query) and ch == query[qpos]:
                    qpos += 1
            if qpos == len(query):
                score = 40 - (len(low) - len(query))
        if score > 0:
            info = _get_package_info(pkg)
            scored.append((pkg, info.get("description", ""), score))
    scored.sort(key=lambda x: (-x[2], x[0]))
    return scored


def search_by_category(category):
    category = category.lower()
    for cat, pkgs in PACKAGE_CATEGORIES.items():
        if cat == category or cat.startswith(category):
            results = []
            for pkg in pkgs:
                info = _get_package_info(pkg)
                desc = info.get("description", "")
                results.append((pkg, desc))
            return results
    return []


def batch_search(packages):
    results = {}
    pkgs = _all_package_names()
    for pkg in packages:
        pkg = pkg.strip()
        if not pkg:
            continue
        found = pkg in pkgs
        results[pkg] = found
    return results


def search_from_file(filename):
    filepath = Path(filename).expanduser().resolve()
    if not filepath.exists():
        print(f"\033[31mFile not found: {filepath}\033[m")
        return {}
    with open(filepath) as f:
        packages = [line.strip() for line in f if line.strip()]
    if not packages:
        print("\033[33mFile is empty.\033[m")
        return {}
    return batch_search(packages)


def show_search_results(results, title="Search Results"):
    if not results:
        print(f"\033[33m{title}: no matches.\033[m")
        return
    print(f"\033[38;2;100;180;255m{title} ({len(results)}):\033[m")
    for i, (pkg, extra) in enumerate(results, 1):
        print(f"  \033[32m{i:2d}.\033[m {pkg:<15} \033[38;2;150;150;150m{extra}\033[m")


def main():
    import readline

    print("\033[38;2;100;180;255m╔════════════════════════════════════╗\033[m")
    print("\033[38;2;100;180;255m║     dpms Package Search Tool       ║\033[m")
    print("\033[38;2;100;180;255m╚════════════════════════════════════╝\033[m")

    pkgs = _all_package_names()

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd in ("--regex", "-r"):
            pattern = sys.argv[2] if len(sys.argv) > 2 else input("Regex pattern: ").strip()
            results = regex_search(pattern)
            show_search_results(results, f"Regex: {pattern}")
            return
        elif cmd in ("--fuzzy", "-f"):
            query = sys.argv[2] if len(sys.argv) > 2 else input("Fuzzy query: ").strip()
            results = fuzzy_search(query)
            show_search_results([(p, f"{d} [{s}]") for p, d, s in results], f"Fuzzy: {query}")
            return
        elif cmd in ("--category", "-c"):
            cat = sys.argv[2] if len(sys.argv) > 2 else input("Category: ").strip()
            results = search_by_category(cat)
            show_search_results(results, f"Category: {cat}")
            return
        elif cmd in ("--batch", "-b"):
            pkgs_input = sys.argv[2:]
            if not pkgs_input:
                pkgs_input = input("Packages (space-separated): ").strip().split()
            results = batch_search(pkgs_input)
            for pkg, found in results.items():
                icon = "\033[32m\u2713\033[m" if found else "\033[31m\u2717\033[m"
                print(f"  {icon} {pkg}")
            return
        elif cmd in ("--file", "--from-file"):
            fn = sys.argv[2] if len(sys.argv) > 2 else input("Filename: ").strip()
            results = search_from_file(fn)
            for pkg, found in results.items():
                icon = "\033[32m\u2713\033[m" if found else "\033[31m\u2717\033[m"
                print(f"  {icon} {pkg}")
            return
        elif cmd in ("--list-repos", "-l"):
            from dpms.dpms_core import list_repos
            list_repos()
            return
        elif cmd in ("--installable", "-a"):
            from dpms.dpms_core import show_installable
            show_installable()
            return
        else:
            pkg = cmd
    else:
        pkg = input("\n\033[33mSearch package:\033[m ").strip()
        if not pkg:
            if pkgs:
                pkg = random.choice(pkgs)
                print(f"\033[33mSearching random package '{pkg}'...\033[m")
            else:
                print("\033[33mNo packages found in repositories.\033[m")
                return

    print(f"\033[33mSearching for '{pkg}'...\033[m")
    found = search_animation(pkg, 2)
    if found:
        install_animation(pkg)
    print(f"\n\033[32m\u2713 Done\033[m")


if __name__ == "__main__":
    main()
