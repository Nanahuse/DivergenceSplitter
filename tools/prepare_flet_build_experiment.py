"""Generate temporary Flet metadata for the CI investigation."""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path

ENTRY = (
    "from divergencesplitter_ui.main import main\n\n"
    'if __name__ == "__main__":\n    raise SystemExit(main())\n'
)
GIT_DEPENDENCIES = {
    "livesplit-bridge-client": "livesplit-bridge-client @ git+https://github.com/Nanahuse/livesplit-bridge-client.git@v0.2.0",
    "windows-capture-device-list": "windows-capture-device-list @ git+https://github.com/Nanahuse/windows-capture-device-list.git@v0.2.0",
}
DEV_PACKAGES = {
    "pep508-git": {
        "divergencesplitter-runtime": "../divergencesplitter-runtime",
        "divergencesplitter": "../divergencesplitter",
    },
}
WINDOWS_DEPENDENCIES = {
    "pep508-git": ["divergencesplitter", "ndi-python>=6.3.2.4"],
}


def add_windows_dependencies(text: str, dependencies: list[str]) -> str:
    """Replace or create the Windows Flet table with a complete dependency list."""
    lines = text.splitlines()
    starts = [
        i for i, line in enumerate(lines) if line.strip() == "[tool.flet.windows]"
    ]
    if len(starts) > 1:
        raise ValueError("duplicate [tool.flet.windows] tables")
    existing = []
    if starts:
        existing = tomllib.loads(text)["tool"]["flet"]["windows"].get(
            "dependencies", []
        )
    unique_dependencies = list(dict.fromkeys([*existing, *dependencies]))
    table = (
        "[tool.flet.windows]\ndependencies = [\n"
        + "".join(f'    "{dep}",\n' for dep in unique_dependencies)
        + "]\n"
    )
    if starts:
        start = starts[0]
        end = next(
            (i for i in range(start + 1, len(lines)) if lines[i].startswith("[")),
            len(lines),
        )
        lines[start:end] = table.rstrip().splitlines()
        return "\n".join(lines) + "\n"
    return text.rstrip() + "\n\n" + table


def prepare_metadata(
    ui_pyproject: Path, runtime_pyproject: Path, ui_dir: Path, mode: str
) -> None:
    if mode not in DEV_PACKAGES:
        raise ValueError(f"unsupported metadata mode: {mode}")
    ui_text = ui_pyproject.read_text(encoding="utf-8")
    ui_dir.joinpath("src", "main.py").write_text(ENTRY, encoding="utf-8")
    ui_text += '\n\n[tool.flet.app]\npath = "src"\nmodule = "main"\n'
    dev = DEV_PACKAGES[mode]
    ui_text += "\n[tool.flet.dev_packages]\n"
    ui_text += "".join(f'{name} = "{path}"\n' for name, path in dev.items())
    ui_text = add_windows_dependencies(ui_text, WINDOWS_DEPENDENCIES[mode])
    # Flet 1.0.0 has --no-compile-packages, but no --no-cleanup-packages.
    # Keep this experiment's Windows-only metadata explicit and runner-local.
    ui_text += "\n[tool.flet.windows.compile]\npackages = false\n"
    ui_text += "\n[tool.flet.windows.cleanup]\npackages = false\n"

    runtime_text = runtime_pyproject.read_text(encoding="utf-8")
    if mode == "pep508-git":
        runtime_data = tomllib.loads(runtime_text)
        deps = []
        for dependency in runtime_data["project"]["dependencies"]:
            package_name, separator, marker = dependency.partition(";")
            replacement = GIT_DEPENDENCIES.get(package_name.strip())
            if replacement and separator:
                replacement += f";{marker}"
            deps.append(replacement or dependency)
        runtime_data["project"]["dependencies"] = deps
        # Keep formatting and unrelated metadata; replace only the dependency array.
        project_start = runtime_text.index("[project]")
        match = re.search(r"dependencies\s*=\s*\[", runtime_text[project_start:])
        if match is None:
            raise ValueError("Runtime project dependencies list was not found")
        start = project_start + match.start()
        end = runtime_text.index("]", project_start + match.end()) + 1
        rendered = (
            "dependencies = [\n" + "".join(f'    "{dep}",\n' for dep in deps) + "]"
        )
        runtime_text = runtime_text[:start] + rendered + runtime_text[end:]
        source_start = runtime_text.find("\n[tool.uv.sources]")
        if source_start >= 0:
            source_end = runtime_text.find("\n[", source_start + 1)
            runtime_text = runtime_text[:source_start] + (
                runtime_text[source_end:] if source_end >= 0 else "\n"
            )

    ui_pyproject.write_text(ui_text, encoding="utf-8")
    runtime_pyproject.write_text(runtime_text, encoding="utf-8")
    tomllib.loads(ui_text)
    tomllib.loads(runtime_text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=sorted(DEV_PACKAGES))
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    ui_dir = args.root / "packages" / "divergencesplitter-ui"
    prepare_metadata(
        ui_dir / "pyproject.toml",
        args.root / "packages" / "divergencesplitter-runtime" / "pyproject.toml",
        ui_dir,
        args.mode,
    )


if __name__ == "__main__":
    main()
