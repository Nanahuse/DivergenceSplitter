"""PyInstaller entry point that launches the desktop UI.

The workspace registers the same function as the ``divergencesplitter-ui``
console script, so the frozen executable behaves identically to the script.
"""

from divergencesplitter_ui.main import main

if __name__ == "__main__":
    raise SystemExit(main())
