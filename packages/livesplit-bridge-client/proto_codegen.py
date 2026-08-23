from __future__ import annotations

import shutil
import sys
from pathlib import Path

from grpc_tools import protoc

EMBEDDED_PROTO_DIRECTORY = "_bridge_proto"


def find_proto_root(project_root: Path) -> Path:
    candidates = (
        project_root.parents[1] / "external" / "LiveSplit.Bridge" / "proto",
        project_root / EMBEDDED_PROTO_DIRECTORY,
    )
    for candidate in candidates:
        if (candidate / "livesplit" / "bridge" / "v1" / "bridge.proto").is_file():
            return candidate
    raise RuntimeError(
        "LiveSplit.Bridge protocol schemas were not found. "
        "Initialize the submodule with `git submodule update --init --recursive`."
    )


def generate_proto(proto_root: Path, output: Path) -> None:
    proto_files = sorted(proto_root.rglob("*.proto"))
    if not proto_files:
        raise RuntimeError(f"No proto files found below {proto_root}")

    generated_root = output / "livesplit"
    if generated_root.exists():
        shutil.rmtree(generated_root)
    output.mkdir(parents=True, exist_ok=True)

    result = protoc.main(
        [
            "grpc_tools.protoc",
            f"-I{proto_root}",
            f"--python_out={output}",
            f"--pyi_out={output}",
            *[str(path) for path in proto_files],
        ]
    )
    if result:
        raise RuntimeError(f"protoc failed with exit code {result}")

    for directory in (
        output / "livesplit",
        output / "livesplit" / "bridge",
        output / "livesplit" / "bridge" / "v1",
    ):
        (directory / "__init__.py").touch()


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    project_root = Path(__file__).resolve().parent
    output = Path(arguments[0]).resolve() if arguments else project_root / "src"
    try:
        generate_proto(find_proto_root(project_root), output)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
