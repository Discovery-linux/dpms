# dpms_confirm.py — port of zypper's Confirm.ycp
#
# Confirmation routines: root checks, delete prompts.

import os

from rich import print as rprint
from rich.prompt import Confirm as RichConfirm

from . import config


def must_be_root():
    """Check if running as root. If not, warn and ask to continue.

    Returns True if running as root or user confirms they want to
    proceed anyway (even though things may not work properly).

    Port of ``Confirm.ycp`` ``MustBeRoot()``.
    """
    if config.IS_ROOT:
        return True

    rprint()
    rprint("[bold red]Root Privileges Needed[/bold red]")
    rprint(
        "[yellow]This operation must be run as root.\n"
        "If you continue, it may not function properly.\n"
        "For example, some files can be read improperly\n"
        "and it is unlikely that settings can be written.[/yellow]"
    )
    rprint()

    ok = RichConfirm.ask("Continue anyway?", default=False)
    if ok:
        rprint("[yellow]NOT running as root![/yellow]")
        return True
    return False


def delete(item=None):
    """Ask for deletion confirmation.

    Port of ``Confirm.ycp`` ``DeleteSelected()`` / ``Delete()``.

    Returns True if the user confirms the deletion.
    """
    if item:
        return RichConfirm.ask(
            f"[yellow]Really delete '[bold]{item}[/bold]'?[/yellow]",
            default=False,
        )
    return RichConfirm.ask(
        "[yellow]Really delete selected entry?[/yellow]",
        default=False,
    )


delete_selected = delete
