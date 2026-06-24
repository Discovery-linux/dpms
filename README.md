# DPMS - Discovery Package Management System

A lightweight, cross-platform package manager by **The xDpms Team**.
Supports **CLI**, **TUI** (Textual rescue shell), and **GUI** (PyQt5) interfaces.

---

## Quick Start

```bash
cd ~/dpms
# Set a dev root so you don't need root access:
export DPMS_ROOT=~/system_root

# Install a package from a local file:
python3 -m dpms.dpms --install myapp-1.0.0-x86_64.dp.tar.xz

# Install by name (looks in dpms/packages/):
python3 -m dpms.dpms --install myapp

# List installed packages:
python3 -m dpms.dpms --list

# Remove:
python3 -m dpms.dpms --uninstall myapp
```

---

## Package Management

| Command | Short | Description |
|---------|-------|-------------|
| `--install PKG` | `-i` | Install a package (local file, URL, or name from repository) |
| `--uninstall PKG` | `-r` | Remove an installed package (removes tracked files) |
| `--list` | `-l`, `-inpc`, `--installed` | List installed packages with file counts |
| `--info PKG` | `-I` | Show package metadata + install status |
| `--files PKG` | `-f` | List every file installed by a package |
| `--verify PKG` | `-V` | Check all installed files still exist |
| `--search PKG` | `-s` | Animated search across repositories |
| `--installable` | `-a` | Show all packages available in repositories |

## Archive & Packaging

| Command | Description |
|---------|-------------|
| `--maketar FOLDER [NAME] [VERSION] [ARCH]` | Create a `.dp.tar.xz` package from a folder (arch auto-detected) |
| `--rc N` | Mark package as release candidate (use with `--maketar`) |
| `--tar FOLDER` | Create a plain `.tar.xz` archive from a folder |

## Repository Management

| Command | Description |
|---------|-------------|
| `--add-repo NAME URL` | Add a new repository |
| `--remove-repo NAME` | Remove a repository |
| `--toggle-repo NAME` | Enable / disable a repository |
| `--repo-list` / `--list-repo [NAME]` | List all repos, or show packages from a specific repo |
| `--sync` / `-S` | Check connectivity to all enabled repositories |

## Utilities

| Command | Short | Description |
|---------|-------|-------------|
| `--rescue` | `-R` | Launch the rescue TUI shell (Textual) |
| `--gui` | | Launch the PyQt5 GUI (if installed) |
| `--reset` | | Reset DPMS configuration |
| `--get` | | Run dpms-get sub-CLI |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DPMS_ROOT` | `/` | Install root for development (e.g., `~/system_root`). When `/`, operations auto-escalate via `sudo`/`doas` |

## Privilege Escalation

When `INSTALL_ROOT_DIR` is `/` (the default), operations that modify the system
(`--install`, `--uninstall`, `--reset`) automatically re-execute with `sudo`
(or `doas` if available). Set `DPMS_ROOT` to a user-writable directory to
skip sudo for development:

```bash
export DPMS_ROOT=~/system_root
python3 -m dpms.dpms --install myapp-1.0.0-x86_64.dp.tar.xz
```

Read-only operations (`--list`, `--info`, `--files`, `--verify`, `--repo-list`,
`--installable`) never need root.

---

## Package Format

DPMS packages are `.tar.xz` archives with a `.dp` extension:

- **Stable**: `name-version-arch.dp.tar.xz`
  - e.g., `ripgrep-13.0.0-x86_64.dp.tar.xz`
- **Release Candidate**: `name-version-arch.dp-rcN.tar.xz`
  - e.g., `ripgrep-13.0.0-x86_64.dp-rc1.tar.xz`

Official DPMS package repository:
**https://github.com/Discovery-linux/Dpms--pkg.git**

Archives are extracted directly to the install root. Each installed package has a
file list recorded in `/var/lib/dp/installed/<name>` for clean uninstallation.

---

## Installation Tracking

DPMS tracks every file a package installs:

```
/var/lib/dp/installed/<pkgname>    ← list of installed file paths
```

On uninstall, DPMS reads this list, removes each file, and cleans up empty
directories. Use `--verify PKG` to check all tracked files still exist.

---

## Architecture

| Platform | Detected Arch | Example |
|----------|--------------|---------|
| Linux x86_64 | `x86_64` | `myapp-1.0.0-x86_64.dp.tar.xz` |
| Linux ARM64 | `aarch64` | `myapp-1.0.0-aarch64.dp.tar.xz` |
| macOS Intel | `x86_64` | `myapp-1.0.0-x86_64.dp.tar.xz` |
| macOS Apple Silicon | `aarch64` | `myapp-1.0.0-aarch64.dp.tar.xz` |

---

## Development

```bash
# Run from source:
cd ~/dpms
export DPMS_ROOT=~/system_root
python3 -m dpms.dpms --help

# Syntax check:
python3 -m py_compile dpms/dpms.py
```

---

Made by:
- **Archit Kala** (Legendary maintainer and  developer)
- **Kevin Dan Matthew** (lead Developer)
