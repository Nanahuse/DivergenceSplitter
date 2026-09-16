"""Generate the UI version module from its project metadata."""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path


def generate_ui_version(pyproject: Path, output: Path) -> str:
    """Write the deterministic application version module and return its version."""
    metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    version = metadata.get("project", {}).get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError(f"[project].version is missing or invalid in {pyproject}")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        '"""Generated application version. Do not edit manually."""\n\n'
        f"VERSION = {json.dumps(version)}\n",
        encoding="utf-8",
        newline="\n",
    )
    return version


def main() -> None:
    parser = argparse.ArgumentParser()
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
