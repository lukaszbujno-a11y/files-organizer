from __future__ import annotations

import subprocess
from pathlib import Path


def pick_folder(prompt: str) -> Path | None:
    """Open a native macOS folder picker. Returns None if the user cancels."""
    script = f'POSIX path of (choose folder with prompt "{prompt}")'
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())
