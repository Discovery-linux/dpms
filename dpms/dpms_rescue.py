import os
import shutil
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, RichLog
from textual import on

from . import config
from .dpms_core import (
    INSTALL_ROOT_DIR, DP_DB_DIR, clean_temp_files, verify_repo_list
)


def cmd_help():
    return (
        "[bold yellow]Commands:[/bold yellow]\n"
        "  [green]check[/green]       Check/create DPMS directories\n"
        "  [green]clean[/green]       Clean temporary files\n"
        "  [green]verify[/green]      Verify repository list\n"
        "  [green]reset[/green]       Reset DPMS configuration\n"
        "  [green]list[/green]        List installed packages\n"
        "  [green]help[/green]        Show this help\n"
        "  [green]exit[/green]        Exit rescue shell"
    )


def cmd_check():
    out = []
    for name, path in [("Config dir", os.path.dirname(config.DPMS_PASSWORD_FILE)),
                       ("Install root", INSTALL_ROOT_DIR),
                       ("Repository dir", config.REPOSITORY_DIR),
                       ("DB dir", DP_DB_DIR)]:
        exists = os.path.exists(path)
        out.append(f"{'[green]\u2713' if exists else '[red]\u2717'} {name}: {path}")
        if not exists:
            try:
                os.makedirs(path, exist_ok=True)
                out.append("  [green]Created[/green]")
            except Exception as e:
                out.append(f"  [red]Failed: {e}[/red]")
    return "\n".join(out)


def cmd_clean():
    clean_temp_files()
    return "[green]\u2713 Temporary files cleaned[/green]"


def cmd_verify():
    verify_repo_list()
    return "[green]\u2713 Repository list verified[/green]"


def cmd_reset():
    dpms_dir = os.path.join(os.path.expanduser('~'), '.dpms')
    if os.path.exists(dpms_dir):
        shutil.rmtree(dpms_dir)
    return "[green]\u2713 DPMS config reset[/green]"


def cmd_list():
    db_dir = DP_DB_DIR
    if not os.path.exists(db_dir):
        return "[yellow]No packages installed[/yellow]"
    pkgs = sorted(os.listdir(db_dir))
    if not pkgs:
        return "[yellow]No packages installed[/yellow]"
    lines = "[cyan]Installed packages:[/cyan]"
    for p in pkgs:
        list_path = os.path.join(db_dir, p)
        count = 0
        try:
            with open(list_path) as f:
                count = sum(1 for _ in f)
        except Exception:
            pass
        lines += f"\n  \u2022 {p} ({count} files)"
    return lines


COMMANDS = {
    "help": cmd_help,
    "check": cmd_check,
    "clean": cmd_clean,
    "verify": cmd_verify,
    "reset": cmd_reset,
    "list": cmd_list,
    "exit": None,
}


class RescueApp(App):
    TITLE = "DPMS Rescue Shell"
    CSS = """
    #log { height: 1fr; border: none; margin: 0 1; }
    #input { dock: bottom; margin: 0 1 1 1; }
    """

    def compose(self):
        yield Header(show_clock=True)
        yield RichLog(id="log", highlight=True, markup=True, wrap=True)
        yield Input(id="input", placeholder="Type a command (help for list)")
        yield Footer()

    def on_mount(self):
        log = self.query_one("#log", RichLog)
        log.write("[bold yellow]DPMS Rescue Shell[/bold yellow]")
        log.write("[dim]Type [green]help[/green] for available commands, [green]exit[/green] to quit.[/dim]\n")
        self.query_one("#input", Input).focus()
        log.scroll_end(animate=False)

    @on(Input.Submitted)
    def handle_command(self, event: Input.Submitted):
        log = self.query_one("#log", RichLog)
        inp = self.query_one("#input", Input)
        raw = event.value.strip()
        inp.clear()

        log.write(f"[bold blue]>[/bold blue] {raw}")

        if not raw:
            return

        parts = raw.split()
        cmd = parts[0].lower()

        if cmd == "exit":
            log.write("[green]Exiting rescue shell. Stay safe![/green]")
            self.exit()
            return

        if cmd in COMMANDS:
            fn = COMMANDS[cmd]
            if fn:
                result = fn()
                log.write(result)
            log.write("")
        else:
            log.write(f"[red]Unknown command: {cmd}[/red]")
            log.write("[dim]Type [green]help[/green] for available commands[/dim]\n")


def run_rescue_tui():
    app = RescueApp()
    app.run()
