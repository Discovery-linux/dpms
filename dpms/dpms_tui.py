from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, ListView, ListItem, Input, Button, RichLog, Label, TabbedContent, TabPane
from textual.containers import Horizontal, Vertical, Container
from textual.binding import Binding
from textual import on

import os
import sys
from . import dpms_core as core
from .config import needs_privileges, reexec_with_privileges, PRIV_ESCALATOR, IS_ROOT
from . import dpms_history as history_mod
from . import dpms_logging

log = dpms_logging.get_logger("dpms")


def _ensure_priv(op_name):
    if needs_privileges(op_name):
        if PRIV_ESCALATOR:
            log.warning("'%s' needs root — re-execing with %s", op_name, PRIV_ESCALATOR)
            from rich import print as rprint
            rprint(f"[yellow]'{op_name}' needs root — re-execing with:[/yellow]")
            rprint(f"  [bold]{PRIV_ESCALATOR} {' '.join(sys.argv)}[/bold]")
            sys.stdout.flush()
            sys.stderr.flush()
            cmd = [PRIV_ESCALATOR] + sys.argv
            os.execvp(PRIV_ESCALATOR, cmd)
        else:
            return ("%s needs root. Install sudo or doas, "
                    "or set DPMS_ROOT to a user-writable path.") % op_name
    return None


class Dashboard(Screen):
    BINDINGS = [
        Binding("p", "go_packages", "Packages"),
        Binding("r", "go_repos", "Repos"),
        Binding("h", "go_history", "History"),
        Binding("q", "quit", "Quit"),
    ]

    def compose(self):
        yield Header(show_clock=True)
        yield Container(
            Static("[bold cyan]DPMS Package Manager[/bold cyan]", id="title"),
            Static("v1.1.0 — cross-platform package manager", id="subtitle"),
            Static(""),
            Button("Package Manager", id="btn-packages", variant="primary"),
            Button("Repository Manager", id="btn-repos", variant="default"),
            Button("Transaction History", id="btn-history", variant="default"),
            Button("Quit", id="btn-quit", variant="error"),
            id="menu",
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "btn-packages":
            self.app.push_screen(Packages())
        elif event.button.id == "btn-repos":
            self.app.push_screen(Repos())
        elif event.button.id == "btn-history":
            self.app.push_screen(History())
        elif event.button.id == "btn-quit":
            self.app.exit()

    def action_go_packages(self):
        self.app.push_screen(Packages())

    def action_go_repos(self):
        self.app.push_screen(Repos())

    def action_go_history(self):
        self.app.push_screen(History())

    def action_quit(self):
        self.app.exit()

    def on_mount(self):
        self.query_one("#title").styles.text_align = "center"
        self.query_one("#subtitle").styles.text_align = "center"
        self.query_one("#menu").styles.align = ("center", "middle")


# TODO: this whole class is a mess, needs proper state management
class Packages(Screen):
    BINDINGS = [
        Binding("q", "app.pop_screen", "Back"),
        Binding("i", "show_installed", "Installed"),
        Binding("a", "show_available", "Available"),
        Binding("slash", "focus_search", "Search"),
    ]

    def compose(self):
        yield Header(show_clock=True)
        yield Container(
            Horizontal(
                Button("Installed", id="btn-installed", variant="primary"),
                Button("Available", id="btn-available", variant="default"),
                Input(placeholder="Search packages...", id="search-input"),
                id="pkg-toolbar",
            ),
            RichLog(id="pkg-list", highlight=True, markup=True, wrap=True),
            Horizontal(
                Button("Install", id="btn-install", variant="success"),
                Button("Remove", id="btn-remove", variant="error"),
                Button("Info", id="btn-info", variant="default"),
                Button("Back", id="btn-back", variant="default"),
                id="pkg-actions",
            ),
            Static("", id="pkg-status"),
        )
        yield Footer()

    def on_mount(self):
        self._mode = "installed"
        self._refresh()

    def _refresh(self):
        log_area = self.query_one("#pkg-list", RichLog)
        log_area.clear()
        if self._mode == "installed":
            log_area.write("[bold cyan]Installed Packages:[/bold cyan]\n")
            try:
                db = core.DP_DB_DIR
                if os.path.exists(db):
                    for p in sorted(os.listdir(db)):
                        log_area.write(f"  \u2022 [green]{p}[/green]")
                else:
                    log_area.write("  [yellow]No packages installed[/yellow]")
            except Exception as e:
                log_area.write(f"  [red]Error: {e}[/red]")
        else:
            log_area.write("[bold cyan]Available Packages:[/bold cyan]\n")
            repo = core.load_repo_list()
            if not repo:
                log_area.write("  [yellow]No repositories configured[/yellow]")
            else:
                for name, info in repo.items():
                    ver = info.get('version', '?')
                    desc = info.get('description', '')
                    log_area.write(f"  [green]{name}[/green] [dim]{ver}[/dim]  {desc}")

    def action_show_installed(self):
        self._mode = "installed"
        self.query_one("#btn-installed", Button).variant = "primary"
        self.query_one("#btn-available", Button).variant = "default"
        self._refresh()

    def action_show_available(self):
        self._mode = "available"
        self.query_one("#btn-installed", Button).variant = "default"
        self.query_one("#btn-available", Button).variant = "primary"
        self._refresh()

    def action_focus_search(self):
        self.query_one("#search-input", Input).focus()

    @on(Input.Submitted, "#search-input")
    def on_search(self, event: Input.Submitted):
        query = event.value.strip()
        if not query:
            self._refresh()
            return
        log_area = self.query_one("#pkg-list", RichLog)
        log_area.clear()
        log_area.write(f"[bold cyan]Search Results for '{query}':[/bold cyan]\n")
        repo = core.load_repo_list()
        found = False
        for name, info in repo.items():
            if query.lower() in name.lower() or query.lower() in info.get('description', '').lower():
                ver = info.get('version', '?')
                desc = info.get('description', '')
                log_area.write(f"  [green]{name}[/green] [dim]{ver}[/dim]  {desc}")
                found = True
        if not found:
            log_area.write("  [yellow]No matching packages[/yellow]")

    @on(Button.Pressed, "#btn-install")
    def on_install(self):
        log_area = self.query_one("#pkg-list", RichLog)
        log_area.write("\n[yellow]Enter package name in search box, then press Install again[/yellow]")

    @on(Button.Pressed, "#btn-remove")
    def on_remove(self):
        log_area = self.query_one("#pkg-list", RichLog)
        log_area.write("\n[yellow]Enter package name in search box, then press Remove again[/yellow]")

    @on(Button.Pressed, "#btn-info")
    def on_info(self):
        inp = self.query_one("#search-input", Input)
        name = inp.value.strip()
        if not name:
            return
        log_area = self.query_one("#pkg-list", RichLog)
        log_area.clear()
        try:
            from io import StringIO
            import sys as _sys
            _sys.stdout = StringIO()
            try:
                core.package_info(name)
            finally:
                out = _sys.stdout.getvalue()
                _sys.stdout = _sys.__stdout__
            log_area.write(out or f"[yellow]No info for '{name}'[/yellow]")
        except Exception as e:
            log_area.write(f"[red]Error: {e}[/red]")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-installed":
            self.action_show_installed()
        elif event.button.id == "btn-available":
            self.action_show_available()
        elif event.button.id == "btn-install":
            err = _ensure_priv('install')
            if err:
                self.query_one("#pkg-list", RichLog).write(f"[red]{err}[/red]")
                return
            inp = self.query_one("#search-input", Input)
            name = inp.value.strip()
            if name:
                log_area = self.query_one("#pkg-list", RichLog)
                try:
                    core.install_package(name)
                    log_area.write(f"[green]Installed {name}[/green]")
                    if self._mode == "installed":
                        self._refresh()
                except Exception as e:
                    log_area.write(f"[red]Install failed: {e}[/red]")
        elif event.button.id == "btn-remove":
            err = _ensure_priv('uninstall')
            if err:
                self.query_one("#pkg-list", RichLog).write(f"[red]{err}[/red]")
                return
            inp = self.query_one("#search-input", Input)
            name = inp.value.strip()
            if name:
                log_area = self.query_one("#pkg-list", RichLog)
                try:
                    core.remove_package(name)
                    log_area.write(f"[green]Removed {name}[/green]")
                    if self._mode == "installed":
                        self._refresh()
                except Exception as e:
                    log_area.write(f"[red]Remove failed: {e}[/red]")


class Repos(Screen):
    BINDINGS = [
        Binding("q", "app.pop_screen", "Back"),
        Binding("s", "sync", "Sync"),
    ]

    def compose(self):
        yield Header(show_clock=True)
        yield Container(
            Horizontal(
                Button("Sync All", id="btn-sync", variant="primary"),
                Button("Toggle", id="btn-toggle", variant="default"),
                Button("Back", id="btn-back", variant="default"),
                id="repo-toolbar",
            ),
            RichLog(id="repo-list", highlight=True, markup=True, wrap=True),
            Horizontal(
                Input(placeholder="Repo name", id="repo-name"),
                Input(placeholder="Repo URL", id="repo-url"),
                id="repo-inputs",
            ),
            Horizontal(
                Button("Add", id="btn-add", variant="success"),
                Button("Remove", id="btn-remove-repo", variant="error"),
                id="repo-actions",
            ),
            Static("", id="repo-status"),
        )
        yield Footer()

    def on_mount(self):
        self._refresh()

    def _refresh(self):
        log_area = self.query_one("#repo-list", RichLog)
        log_area.clear()
        log_area.write("[bold cyan]Repositories:[/bold cyan]\n")
        try:
            repo = core.load_repo_list()
            if not repo:
                log_area.write("  [yellow]No repositories configured[/yellow]")
            else:
                for name, info in repo.items():
                    url = info.get('url', '')
                    enabled = info.get('enabled', True)
                    status = "[green]\u2713[/green]" if enabled else "[red]\u2717[/red]"
                    log_area.write(f"  {status} [bold]{name}[/bold] [dim]{url}[/dim]")
        except Exception as e:
            log_area.write(f"  [red]Error: {e}[/red]")

    def action_sync(self):
        err = _ensure_priv('sync')
        if err:
            self.query_one("#repo-list", RichLog).write(f"[red]{err}[/red]")
            return
        log_area = self.query_one("#repo-list", RichLog)
        log_area.write("\n[cyan]Syncing repositories...[/cyan]")
        try:
            core.sync_repos()
            log_area.write("[green]Sync complete[/green]")
        except Exception as e:
            log_area.write(f"[red]Sync failed: {e}[/red]")

    def on_button_pressed(self, event: Button.Pressed):
        log_area = self.query_one("#repo-list", RichLog)
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-sync":
            self.action_sync()
        elif event.button.id == "btn-toggle":
            err = _ensure_priv('install')
            if err:
                log_area.write(f"[red]{err}[/red]")
                return
            name = self.query_one("#repo-name", Input).value.strip()
            if name:
                try:
                    core.toggle_repo(name)
                    log_area.write(f"[green]Toggled {name}[/green]")
                    self._refresh()
                except Exception as e:
                    log_area.write(f"[red]Error: {e}[/red]")
        elif event.button.id == "btn-add":
            err = _ensure_priv('install')
            if err:
                log_area.write(f"[red]{err}[/red]")
                return
            name = self.query_one("#repo-name", Input).value.strip()
            url = self.query_one("#repo-url", Input).value.strip()
            if name and url:
                try:
                    core.add_repo(name, url)
                    log_area.write(f"[green]Added repo {name}[/green]")
                    self._refresh()
                except Exception as e:
                    log_area.write(f"[red]Error: {e}[/red]")
        elif event.button.id == "btn-remove-repo":
            err = _ensure_priv('install')
            if err:
                log_area.write(f"[red]{err}[/red]")
                return
            name = self.query_one("#repo-name", Input).value.strip()
            if name:
                try:
                    core.remove_repo(name)
                    log_area.write(f"[green]Removed repo {name}[/green]")
                    self._refresh()
                except Exception as e:
                    log_area.write(f"[red]Error: {e}[/red]")


class History(Screen):
    BINDINGS = [
        Binding("q", "app.pop_screen", "Back"),
    ]

    def compose(self):
        yield Header(show_clock=True)
        yield Container(
            RichLog(id="hist-list", highlight=True, markup=True, wrap=True),
            Button("Back", id="btn-back", variant="default"),
        )
        yield Footer()

    def on_mount(self):
        log_area = self.query_one("#hist-list", RichLog)
        log_area.write("[bold cyan]Transaction History:[/bold cyan]\n")
        try:
            history = history_mod._load()
            if not history:
                log_area.write("  [yellow]No transactions yet[/yellow]")
            else:
                for tx in reversed(history):
                    action = tx["action"]
                    if action == "install":
                        style = "green"
                    elif action == "remove":
                        style = "red"
                    else:
                        style = "white"
                    ts = tx.get("timestamp", "")[:19]
                    pkg = tx["package"]
                    ver = tx.get("version", "")
                    log_area.write(
                        f"  [{style}]{action:>8}[/{style}]  "
                        f"[dim]{ts}[/dim]  "
                        f"[bold]{pkg}[/bold]  "
                        f"[dim]{ver}[/dim]"
                    )
        except Exception as e:
            log_area.write(f"  [red]Error: {e}[/red]")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "btn-back":
            self.app.pop_screen()


class DPMS_App(App):
    TITLE = "DPMS"
    CSS = """
    Screen {
        layout: vertical;
    }
    Container {
        height: 1fr;
    }
    Header {
        background: $primary-background;
    }
    Footer {
        background: $surface;
    }
    RichLog {
        height: 1fr;
        border: solid $primary;
        padding: 0 1;
    }
    Input {
        margin: 0 1;
    }
    Button {
        margin: 1 1;
    }
    Horizontal {
        height: auto;
    }
    #menu {
        align: center middle;
    }
    #menu Button {
        width: 40;
        margin: 1;
    }
    #title {
        text-style: bold;
        text-style: italic;
        color: $primary;
    }
    #pkg-toolbar {
        height: auto;
        margin: 0 0 1 0;
    }
    #pkg-actions {
        height: auto;
        margin: 1 0 0 0;
    }
    #repo-toolbar {
        height: auto;
        margin: 0 0 1 0;
    }
    #repo-inputs {
        height: auto;
        margin: 1 0 1 0;
    }
    #repo-actions {
        height: auto;
    }
    #search-input {
        width: 1fr;
    }
    """

    def compose(self):
        yield Header(show_clock=True)
        yield Container(
            Label("[bold cyan]DPMS Package Manager[/bold cyan]", id="splash"),
            Label("Loading...", id="loading"),
        )
        yield Footer()

    def on_mount(self):
        self.push_screen(Dashboard())


def main():
    app = DPMS_App()
    app.run()


if __name__ == "__main__":
    main()
