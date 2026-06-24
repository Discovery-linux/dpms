#!/usr/bin/env python3
"""dpms-command-help — quick reference for all DPMS commands"""

help_text = """
DPMS Commands — Quick Reference
================================

Log file types
---------------
  Three kinds of .log files are used across a DPMS port repository:

  dlr.log        Discovery Listed Repos — repo-root file containing SHA
                 hashes for verification of the repository contents.

  <name>.log     Per-package metadata — one per port directory, named after
                 the directory (e.g. zstd/zstd.log).  Must set shell variables
                 name, version, release (sourced via bash).

  nft.log        Not From Here — placed inside a port directory to mark it
                 as excluded.  Port-commit will skip any directory containing
                 an nft.log file.

Port-commit (local ports workflow)
-----------------------------------
  --port-commit  |  dpms --get port-commit

  Commit changes to local port directories containing a <name>.log file.

  How it works:
    1. Walks up from cwd to find the git root.
    2. Iterates subdirectories looking for <dirname>.log.
    3. Skips any directory containing nft.log.
    4. Sources the .log file to read name, version, release.
    5. git-adds the directory.
    6. New port  → commits "add <name>"
    7. Updated   → commits "<name> : <version>-<release>"
    8. Unchanged → skipped.

  Example:
    cd /usr/ports/core
    dpms --port-commit

dlr.log verification
---------------------
  --dlr-verify  |  dpms --get dlr-verify

  Verify all SHA hashes listed in the repo-root dlr.log against
  the actual file contents.  Reports MISSING (file not found) and
  FAIL (hash mismatch).  Exits with status 1 on any error.

  Example:
    dpms --dlr-verify

nft.log (excluded directories)
-------------------------------
  --list-nft  |  dpms --get list-nft

  List every subdirectory that contains an nft.log marker file.
  These directories are excluded from port-commit operations.

  Example:
    dpms --list-nft

Package management
-------------------
  --install PKG [PKG ...]   |  -i PKG     Install package(s)
  --uninstall PKG            |  -r PKG     Remove a package
  --reinstall PKG             Reinstall a package
  --upgrade                   |  -u        Upgrade all installed packages
  --downgrade PKG             Downgrade a package
  --download PKG              Download a package archive without installing

dpms-get subcommands:
  install PKG [PKG ...]      Install package(s)
  remove PKG [PKG ...]       Remove package(s)
  purge PKG [PKG ...]        Remove package(s) and config files
  reinstall PKG [PKG ...]    Reinstall package(s)
  upgrade                    Upgrade all installed packages
  dist-upgrade               Distribution upgrade
  download PKG               Download binary package

Searching & info
-----------------
  --search PKG     |  -s PKG     Search for a package (with animation)
  --info PKG       |  -I PKG     Show detailed package info
  --files PKG      |  -f PKG     List files installed by a package
  --verify PKG     |  -V PKG     Verify installed package files exist
  --depends PKG                 Show dependency tree
  --rdepends PKG                Show reverse dependencies
  --what-owns FILE              Find which package owns a file
  --changelog PKG               Show changelog for a package
  --why PKG                     Show why a package is installed
  --compare V1 V2               Compare two version strings
  --check                       Check package integrity
  --verify-all                  Verify all installed packages
  --duplicates                  Find duplicate files across packages

dpms-get subcommands:
  search PKG                   Search for packages
  info PKG                     Show package information
  depends PKG                  Show dependency tree
  rdepends PKG                 Show reverse dependencies
  what-owns PATH               Find which package owns a file
  check                        Verify package integrity
  changelog PKG                Show changelog for a package

Listing
--------
  --list          |  -l / --installed     List installed packages
  --installable   |  -a                   Show all installable packages
  --list-updates                         Show available package updates
  --stats                                Show package statistics

dpms-get subcommands:
  list-updates                   Show available updates
  stats                          Show package statistics

Repository management
----------------------
  --add-repo NAME URL [ARCH]            Add a repository
  --remove-repo NAME                    Remove a repository
  --toggle-repo NAME                    Enable/disable a repository
  --repo-list [NAME]                    List repos or show details
  --list-repo [NAME]                    Alias for --repo-list
  --sync            |  -S               Check connectivity to all repos
  --update          |  -U               Update metadata from all repos
  --repo-priority NAME PRIO             Set repository priority

Locking / holding
------------------
  --lock PKG                            Lock a package (prevent changes)
  --unlock PKG                          Unlock a package
  --locked-list                         Show locked packages
  --hold PKG                            Hold a package (prevent upgrades)
  --unhold PKG                          Release a held package
  --list-held                           Show held packages

Advanced (zypper-style)
------------------------
  --dry-run                             Preview changes without committing
  --force-resolution                    Force dependency resolution
  --no-recommends                       Only required dependencies
  --clean-deps                          Remove orphaned deps on remove
  --clean | --autoremove                Remove orphaned packages

dpms-get subcommands:
  autoremove                         Remove orphaned packages
  satisfy TARGET                     Satisfy dependency strings
  build-dep PKG                      Install build dependencies
  source PKG                         Download source archive
  markauto PKG [PKG ...]             Mark packages as auto-installed
  unmarkauto PKG [PKG ...]           Mark packages as manually installed

Cache / cleanup
----------------
  --clean-cache                         Clean cached packages and repo data

dpms-get subcommands:
  clean                              Erase downloaded archive files
  autoclean / auto-clean             Erase old cached files
  distclean / dist-clean             Erase all caches

Backup / restore
-----------------
  --backup DIR                          Back up package database
  --restore FILE                        Restore package database
  --export-installed FILE               Export installed package list
  --import-installed FILE               Install packages from exported list

System / config
----------------
  --arch                                Show system architecture
  --reset                               Reset DPMS configuration
  --rescue       |  -R                  Rescue / repair mode
  --history                             Show transaction history
  --history-last N                      Show last N transactions
  --feedback                            Send feedback to DPMS team

dpms-get subcommands:
  rescue                             Rescue / repair DPMS installation

TUI / GUI
----------
  --tui           |  -T                  Launch Textual TUI
  --gui                                 Launch Qt GUI

Archive creation
-----------------
  --maketar FOLDER [NAME VERSION [ARCH]]   Create a .dp.tar.xz package
  --tar FOLDER                              Create tar.xz from a folder
  --rc N                                    RC suffix for --maketar

apt-ftparchive-style commands
------------------------------
  --gen-packages DIR           Generate Packages index
  --gen-sources DIR            Generate Sources index
  --gen-contents DIR           Generate Contents file
  --gen-release DIR            Generate Release file with checksums
  --gen-repo DIR               Generate full repo metadata
  --gen-generate CONFIG        Generate repo from config file
  --gen-clean DIR              Clean cache files from a repo dir

Global flags (dpms-get)
-------------------------
  -v / --verbose       Enable verbose output
  -V / --version       Show version
  --exit               Return to DPMS main terminal

dpms-get subcommands:
  update                     Resynchronize package metadata
"""


def show_help():
    print(help_text)


def main():
    show_help()


if __name__ == "__main__":
    main()
