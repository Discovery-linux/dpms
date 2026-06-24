import shutil
import sys
import time
from rich import print as rich_print
from .dpms_core import search_package, install_package


# ugly but works
def search_animation(package, duration=2):
    cols = min(shutil.get_terminal_size().columns if sys.stdout.isatty() else 80, 200)
    cols = max(cols, 40)
    bar_w = cols - 28

    start = time.time()
    end = start + duration
    dots = 0

    while time.time() < end:
        elapsed = time.time() - start
        pct = min(int(elapsed * 100 / duration), 99)
        filled = int(pct * bar_w / 100)
        empty = bar_w - filled

        bar = "\u2588" * filled + "\u2591" * empty
        sys.stdout.write(f"\r\033[38;2;100;180;255mSearching{'.' * ((dots % 3) + 1):<4}\033[m [{bar}] {pct:2d}%")
        sys.stdout.flush()
        dots += 1
        time.sleep(0.05)

    full = "\u2588" * bar_w
    sys.stdout.write(f"\r\033[38;2;100;180;255mSearching...\033[m [{full}] 100%")
    sys.stdout.flush()
    time.sleep(0.3)

    sys.stdout.write("\n")
    results = search_package(package, verbose=False)

    if results:
        msg = f"\033[32m\u2713 Package '{package}' found\033[m"
        found = True
    else:
        msg = f"\033[31m\u2717 Package '{package}' not found\033[m"
        found = False

    sys.stdout.write(f"\n{msg}\n")
    return found


# TODO: this interactive mode is barebones
def interative_search():
    rich_print("[bold cyan]╔════════════════════════════════════╗[/bold cyan]")
    rich_print("[bold cyan]║     dpms Package Search Tool       ║[/bold cyan]")
    rich_print("[bold cyan]╚════════════════════════════════════╝[/bold cyan]")

    import readline
    import random

    PACKAGES = [
        "numpy", "pandas", "requests", "flask", "django",
        "torch", "tensorflow", "scipy", "matplotlib", "fastapi"
    ]
    from .dpms_core import load_repo_list

    repo = load_repo_list()

    pkg = input("\n\033[33mSearch package:\033[m ").strip()
    if not pkg:
        print("\033[33mSearching random package...\033[m")
        pkg = random.choice(list(repo.keys())) if repo else "testapp"

    print(f"\033[33mSearching for '{pkg}'...\033[m")
    found = search_animation(pkg, 2)
    if found:
        rich_print(f"\n[bold yellow]Installing '{pkg}'...[/bold yellow]")
        install_package(pkg)
    print("\033[32m\u2713 Done\033[m")
