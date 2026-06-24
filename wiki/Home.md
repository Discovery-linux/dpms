# DPMS — Discovery Package Manager

A lightweight cross-platform package manager by **The Discovery Team**.

- **CLI** (command-line), **TUI** (Textual rescue shell), **GUI** (PyQt5)
- Tracks every installed file for clean removal
- Supports local packages, remote URLs, and git-backed repositories

## Quick start

```bash
export DPMS_ROOT=~/system_root
dpms --install myapp-1.0.0-x86_64.dp.tar.xz
dpms --list
dpms --uninstall myapp
```

## Pages

- [Installation](Installation)
- [Commands](Commands)
- [Package format](Package-Format)
- [dm version manager](dm)
