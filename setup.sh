#!/bin/bash

# DPMS Setup — ncurses menuconfig-style installer

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- detect ncurses tool ---
if command -v dialog &>/dev/null; then
    DIAlog=dialog
elif command -v whiptail &>/dev/null; then
    DIAlog=whiptail
else
    echo "Neither dialog nor whiptail found — falling back to text menu."
    _simple_menu=1
fi

# --- helpers ---
_height=18
_width=60
_menu_height=10

_msgbox()   { $DIAlog --msgbox "$1" $_height $_width 2>&1; }
_yesno()    { $DIAlog --yesno "$1" $_height $_width 2>&1; }
_inputbox() { $DIAlog --inputbox "$1" $_height $_width "$2" 2>&1; }

_install_deps() {
    python3 -m pip install --upgrade pip
    python3 -m pip install -e "$SCRIPT_DIR"
}

_install_gui() {
    python3 -m pip install PyQt5
}

_install_tui() {
    # textual is already a dep; just confirm
    :
}

_remove_dpms() {
    local site
    site=$(python3 -c "import site; print(site.getsitepackages()[0])" 2>/dev/null || true)
    if [ -n "$site" ] && [ -d "$site/dpms" ]; then
        rm -rf "$site/dpms"
        rm -f "$site/dpms-"*.dist-info
    fi
    rm -f /usr/local/bin/dpms /usr/local/bin/dpms-tui 2>/dev/null || true
}

_show_about() {
    $DIAlog --title "About DPMS" --msgbox "\
DPMS — Discovery Package Manager
Version 1.1.0

Cross-platform CLI, TUI & GUI package manager.

Authors: Archit & Kevin (THE Discovery Team)
License: MIT" $_height $_width 2>&1
}

_show_done() {
    $DIAlog --title "Done" --msgbox "\
DPMS installed successfully.

You can now run:
  dpms          — CLI
  dpms --tui    — Textual TUI
  dpms-tui      — Textual TUI (direct)
  dpms --gui    — Qt GUI (requires PyQt5)" $_height $_width 2>&1
}

_set_root() {
    local path
    path=$(_inputbox "Set DPMS_ROOT (install target directory):" "$DPMS_ROOT")
    if [ -n "$path" ]; then
        export DPMS_ROOT="$path"
        mkdir -p "$path" 2>/dev/null || true
        if grep -q '^export DPMS_ROOT=' ~/.bashrc 2>/dev/null; then
            sed -i "s|^export DPMS_ROOT=.*|export DPMS_ROOT=$path|" ~/.bashrc
        else
            echo "export DPMS_ROOT=$path" >> ~/.bashrc
        fi
        _msgbox "DPMS_ROOT set to: $path"
    fi
}

_add_default_repos() {
    cat >> "$SCRIPT_DIR/dpms/repo_list.json" <<'REPO_EOF'
{
    "discovery-core": {
        "url": "https://github.com/discoveryos/discovery-packages.git",
        "version": "1.0",
        "description": "Core Discovery OS packages",
        "enabled": true
    }
}
REPO_EOF
    _msgbox "Default repository added."
}

# --- main menu ---
while true; do
    if [ -n "$_simple_menu" ]; then
        echo ""
        echo "=== DPMS Setup ==="
        echo "1) Install DPMS (full)"
        echo "2) Install GUI (PyQt5)"
        echo "3) Set DPMS_ROOT"
        echo "4) Add default repositories"
        echo "5) Remove DPMS"
        echo "6) About"
        echo "7) Exit"
        read -rp "Select [1-7]: " sel
        case "$sel" in
            1) _install_deps; _show_done ;;
            2) _install_gui; _msgbox "GUI dependencies installed." ;;
            3) _set_root ;;
            4) _add_default_repos ;;
            5) _remove_dpms; _msgbox "DPMS removed." ;;
            6) echo "DPMS — Discovery Package Manager v1.1.0"; echo "Authors: Archit & Kevin (THE Discovery Team)"; echo "License: MIT" ;;
            7) break ;;
        esac
    else
        sel=$($DIAlog --clear --title "DPMS Setup" \
            --menu "Choose an option:" $_height $_width $_menu_height \
            1 "Install DPMS (full)" \
            2 "Install GUI (PyQt5)" \
            3 "Set DPMS_ROOT" \
            4 "Add default repositories" \
            5 "Remove DPMS" \
            6 "About" \
            7 "Exit" 2>&1)
        case "$sel" in
            1) _install_deps; _show_done ;;
            2) _install_gui; _msgbox "GUI dependencies installed." ;;
            3) _set_root ;;
            4) _add_default_repos ;;
            5) _remove_dpms; _msgbox "DPMS removed." ;;
            6) _show_about ;;
            7) break ;;
        esac
    fi
done
