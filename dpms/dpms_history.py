import json
import os
import time
from datetime import datetime

HISTORY_DIR = os.path.join(os.path.expanduser("~"), ".cache", "dpms", "history")
HISTORY_FILE = os.path.join(HISTORY_DIR, "transactions.json")


def _ensure_dir():
    os.makedirs(HISTORY_DIR, exist_ok=True)


def _load():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save(history):
    _ensure_dir()
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def record(action, package, version=None, files_count=None, detail=""):
    history = _load()
    tx_id = (history[-1]["id"] + 1) if history else 1
    history.append({
        "id": tx_id,
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z"),
        "action": action,
        "package": package,
        "version": version or "",
        "files": files_count or 0,
        "detail": detail,
    })
    _save(history)
    return tx_id


def show_history(limit=None):
    from rich.table import Table
    from rich.console import Console

    history = _load()
    if not history:
        Console().print("[yellow]No transaction history yet.[/yellow]")
        return

    if limit:
        history = history[-limit:]

    table = Table(title=f"Transaction History ({len(history)} record(s))")
    table.add_column("ID", style="dim")
    table.add_column("Timestamp")
    table.add_column("Action", style="bold")
    table.add_column("Package")
    table.add_column("Version")
    table.add_column("Files")

    for tx in reversed(history):
        action = tx["action"]
        if action == "install":
            action_style = "[green]install[/green]"
        elif action == "remove":
            action_style = "[red]remove[/red]"
        else:
            action_style = action
        ts = tx.get("timestamp", "")[:19]
        if len(tx.get("detail", "")) > 30:
            detail = tx["detail"][:27] + "..."
        else:
            detail = tx.get("detail", "")
        table.add_row(
            str(tx["id"]),
            ts,
            action_style,
            tx["package"],
            tx.get("version", ""),
            str(tx.get("files", "")),
        )
    Console().print(table)


def last_transaction():
    history = _load()
    return history[-1] if history else None
