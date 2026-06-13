"""
main.py — Auto Warfare entry point.

Builds the shell (which registers the worlds and the portal) and runs the Qt
event loop. Run from the project root so ``az`` resolves as a package::

    python -m az.main
"""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from az.shell.app import ShellApp


def main() -> int:
    app = QApplication(sys.argv)
    shell = ShellApp()
    shell.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
