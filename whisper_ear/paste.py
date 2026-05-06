"""Paste text into the active macOS application."""

from __future__ import annotations

import subprocess


def paste_text(text: str) -> None:
    subprocess.run(["pbcopy"], input=text, text=True, check=True)
    subprocess.run(
        ["osascript", "-e", 'tell application "System Events" to keystroke "v" using command down'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

