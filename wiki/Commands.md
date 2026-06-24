# Commands

## Package management

| Command | Short | Description |
|---------|-------|-------------|
| `--install PKG` | `-i` | Install a package (local file, URL, or name) |
| `--uninstall PKG` | `-r` | Remove a package |
| `--list` | `-l` | List installed packages |
| `--info PKG` | `-I` | Show package metadata |
| `--files PKG` | `-f` | List files installed by a package |
| `--verify PKG` | `-V` | Check installed files still exist |
| `--search PKG` | `-s` | Search repositories |
| `--installable` | `-a` | Show all installable packages |
| `--global DIR` | `-g` | Set install root directory |

## Repository management

| Command | Description |
|---------|-------------|
| `--add-repo NAME URL` | Add a repository |
| `--remove-repo NAME` | Remove a repository |
| `--toggle-repo NAME` | Enable/disable a repo |
| `--repo-list` | List all repos |
| `--sync` | Check repo connectivity |

## Packaging

| Command | Description |
|---------|-------------|
| `--maketar FOLDER [NAME VERSION ARCH]` | Create a `.dp.tar.xz` package |
| `--tar FOLDER` | Create a plain `.tar.xz` archive |
| `--rc N` | Mark as release candidate |

## Utilities

| Command | Description |
|---------|-------------|
| `--rescue` | Launch the TUI rescue shell |
| `--gui` | Launch the GUI |
| `--reset` | Reset configuration |
| `--history` | Show transaction history |
| `--backup DIR` | Backup package database |
| `--restore FILE` | Restore from backup |

## Global install

```bash
dpms --install myapp --global /usr/local
```

Installs the package into the specified directory instead of the default root.
