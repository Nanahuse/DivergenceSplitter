"""PyInstaller entry point that launches the desktop UI.

The workspace registers the same function as the ``divergencesplitter-ui``
console script, so the frozen executable behaves identically to the script.
"""

import sys

from divergencesplitter_ui.main import main

if __name__ == "__main__":
    if sys.argv[1:] == ["--check-ndi"]:
        # Exercise the frozen application's binding and DLL loading without UI.
        from divergencesplitter.frame.ndi import detect_ndi_support

        raise SystemExit(0 if detect_ndi_support().available else 1)
    raise SystemExit(main())
