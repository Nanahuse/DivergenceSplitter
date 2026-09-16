"""Generate the UI version module from its project metadata.

``packages/divergencesplitter-ui/pyproject.toml`` is the single authority for
the application version. The Flet bundle does not expose installed distribution
metadata, so the version is materialized into ``_version.py`` from that file and
imported directly at runtime.
"""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path

GENERATED_HEADER = '"""Generated application version. Do not edit manually."""'


def generate_ui_version(pyproject: Path, output: Path) -> str:
    """Write the deterministic application version module and return its version."""

    metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    version = metadata.get("project", {}).get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError(f"[project].version is missing or invalid in {pyproject}")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        f"{GENERATED_HEADER}\n\nVERSION = {json.dumps(version)}\n",
        encoding="utf-8",
        newline="\n",
    )
    return version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()

    ui = args.root / "packages" / "divergencesplitter-ui"
    version = generate_ui_version(
        ui / "pyproject.toml", ui / "src" / "divergencesplitter_ui" / "_version.py"
    )
    print(f"Generated UI VERSION={version}")


if __name__ == "__main__":
    main()
