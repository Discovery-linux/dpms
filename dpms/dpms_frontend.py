import sys
import json
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rich_print

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, Checkbox
from textual.containers import Container
from textual.widget import Widget
from textual import on

console = Console()

try:
    if __package__ is None:
        from dpms_core import save_repo_list, REPO_LIST_FILE
    else:
        from .dpms_core import save_repo_list, REPO_LIST_FILE
except ImportError:
    pass


def print_success(message):
    console.print(f"[bold green]\u2713 SUCCESS:[/bold green] {message}")

def print_error(title, message):
    console.print(f"\n[bold red]\u2716 {title.upper()}:[/bold red] {message}", style="bold")
    sys.exit(1)

def print_action_status(status_type, message, style="blue"):
    console.print(f"[{style}]{status_type.upper():<10}[/{style}] {message}")

def print_warning(message):
    console.print(f"[bold yellow]\u26a0 WARNING:[/bold yellow] {message}")

def display_mirror_list(repo_list):
    rich_print("\n[bold magenta]DPMS Configured Package Repositories:[/bold magenta]")
    
    table = Table(title_style="bold magenta", header_style="bold blue")
    table.add_column("Name", style="bold green", min_width=10)
    table.add_column("Status", style="bold", min_width=8)
    table.add_column("URL", style="cyan")
    table.add_column("Description", style="white")

    for name, repo in repo_list.items():
        status = repo.get('enabled', False)
        status_text = "[bold green]ENABLED[/bold green]" if status else "[bold red]DISABLED[/bold red]"
        
        table.add_row(
            name,
            status_text,
            repo.get('url', 'N/A'),
            repo.get('description', 'No description.')
        )
        
    console.print(table)


class MirrorEntry(Widget):
    mirror_name: str
    
    def __init__(self, name: str, url: str, enabled: bool):
        super().__init__()
        self.mirror_name = name
        self.url = url
        self.initial_enabled = enabled
        self.current_enabled = enabled

    def compose(self) -> ComposeResult:
        yield Checkbox(
            f"[bold magenta]{self.mirror_name}[/bold magenta] [dim]({self.url})[/dim]", 
            value=self.initial_enabled,
            id=f"mirror_{self.mirror_name}"
        )

    @on(Checkbox.Changed)
    def update_status(self, event: Checkbox.Changed):
        self.current_enabled = event.value


class MirrorConfigApp(App):
    BINDINGS = [
        ("q", "quit_app", "Quit (Save & Exit)"),
        ("a", "add_mirror", "Add Mirror (CLI Only)"), 
        ("r", "remove_mirror", "Remove Mirror (CLI Only)") 
    ]
    
    CSS = """
    #mirror-container { padding: 1 2; }
    .mirror-entry { height: 2; margin-bottom: 1; }
    """
    
    def __init__(self, repo_list, **kwargs):
        super().__init__(**kwargs)
        self.original_repo_list = repo_list

    def compose(self) -> ComposeResult:
        yield Header()
        
        yield Container(
            Static("[bold blue]DPMS Mirror Configuration Menu[/bold blue]", classes="title"),
            Static(f"\n[dim]Changes saved to: {REPO_LIST_FILE}[/dim]"),
            id="mirror-container"
        )
        
        for name, repo in self.original_repo_list.items():
            yield MirrorEntry(
                name=name, 
                url=repo['url'], 
                enabled=repo.get('enabled', False)
            )
            
        yield Footer()

    def action_quit_app(self):
        updated_repo_list = self.original_repo_list.copy()
        changed_count = 0
        
        for mirror_entry in self.query(MirrorEntry):
            name = mirror_entry.mirror_name
            new_state = mirror_entry.current_enabled
            
            if updated_repo_list[name].get('enabled') != new_state:
                updated_repo_list[name]['enabled'] = new_state
                changed_count += 1
        
        if changed_count > 0:
            if save_repo_list(updated_repo_list):
                self.notify(f"Saved {changed_count} changes to mirror list.", title="Configuration Saved", severity="information")
            else:
                self.notify("ERROR: Failed to save configuration!", title="CRITICAL ERROR", severity="error", timeout=5)
        else:
            self.notify("No changes detected.", title="Exiting", severity="information")
            
        self.exit()


def run_mirror_config_tui(repo_list):
    try:
        app = MirrorConfigApp(repo_list=repo_list)
        app.run()
    except Exception as e:
        print(f"Oops, TUI failed to launch: {e}")
        sys.exit(1)
