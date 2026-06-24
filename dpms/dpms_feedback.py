# dpms_feedback.py — Feedback collection for DPMS
#
# Collects user feedback via a rich terminal form and saves it locally.

from datetime import datetime
import os
import json

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich import print as rprint
from rich.table import Table

_console = Console()
FEEDBACK_DIR = os.path.expanduser("~/.local/share/dpms/feedback")


def _collect_feedback():
    rprint()
    rprint(Panel.fit(
        "[bold blue]DPMS Feedback[/bold blue]\n"
        "Help us improve DPMS by sharing your thoughts, "
        "bug reports, or feature requests.",
        border_style="blue",
    ))
    rprint()

    sender = Prompt.ask("[bold]Your email[/bold]", default="")
    subject = Prompt.ask("[bold]Subject[/bold]")
    rprint("[bold]Message[/bold] [dim](end with Ctrl+D or a line containing only END)[/dim]")
    rprint("[dim]Type your message below:[/dim]")

    lines = []
    try:
        while True:
            line = input()
            if line.strip() == "END":
                break
            lines.append(line)
    except (EOFError, KeyboardInterrupt):
        pass

    body = "\n".join(lines).strip()
    if not body:
        rprint("[red]No message provided. Aborting.[/red]")
        return None

    rprint()
    summary = Table.grid(padding=(0, 1))
    summary.add_column(style="bold")
    summary.add_column()
    if sender:
        summary.add_row("From:", sender)
    summary.add_row("Subject:", subject)
    summary.add_row("Message:", body[:60] + ("..." if len(body) > 60 else ""))
    summary.add_row("Length:", f"{len(body)} characters")

    rprint(Panel(summary, title="[bold]Summary[/bold]", border_style="cyan"))
    rprint()

    ok = Prompt.ask("Save this feedback?", choices=["y", "n"], default="y")
    if ok != "y":
        rprint("[yellow]Feedback cancelled.[/yellow]")
        return None

    return sender, subject, body


def send_feedback():
    result = _collect_feedback()
    if result is None:
        return False
    sender, subject, body = result

    os.makedirs(FEEDBACK_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(FEEDBACK_DIR, f"feedback_{timestamp}.json")

    feedback = {
        "timestamp": timestamp,
        "sender": sender,
        "subject": subject,
        "body": body,
    }

    with open(path, "w") as f:
        json.dump(feedback, f, indent=2)

    rprint(f"[bold green]Feedback saved to {path}[/bold green]")
    rprint("[dim]Thank you for helping improve DPMS.[/dim]")
    return True
