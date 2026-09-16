"""Flet build entry point for the DivergenceSplitter desktop UI.

Flet requires the packaged application to expose a module-level ``main``
function. All application logic stays in the installed ``divergencesplitter_ui``
package; this wrapper only adapts the process exit code.
"""

from __future__ import annotations

from divergencesplitter_ui.main import main

if __name__ == "__main__":
    raise SystemExit(main())
