"""Generate the UI version module from the UI project metadata.

The UI package directory is the root: its ``pyproject.toml`` is the single
authority for the application version, and the module is written to that
package's ``src/divergencesplitter_ui/_version.py``. The Flet bundle does not
expose installed distribution metadata, so the version is materialized there and
imported directly at runtime.
"""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
UI_PACKAGE = REPO_ROOT / "packages" / "divergencesplitter-ui"
VERSION_MODULE = Path("src") / "divergencesplitter_ui" / "_version.py"
GENERATED_HEADER = '"""Generated application version. Do not edit manually."""'


def generate_ui_version(ui_root: Path) -> str:
    """Write the deterministic version module for the UI package and return it."""

    pyproject = ui_root / "pyproject.toml"
    metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    version = metadata.get("project", {}).get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError(f"[project].version is missing or invalid in {pyproject}")

    output = ui_root / VERSION_MODULE
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        f"{GENERATED_HEADER}\n\nVERSION = {json.dumps(version)}\n",
        encoding="utf-8",
        newline="\n",
    )
    return version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=UI_PACKAGE)
    args = parser.parse_args()

    version = generate_ui_version(args.root)
    print(f"Generated UI VERSION={version}")


if __name__ == "__main__":
    main()
