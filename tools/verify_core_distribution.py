"""Verify the installed core distribution from outside the workspace."""

import argparse
import tarfile
import zipfile
from importlib import metadata, util
from pathlib import Path, PurePosixPath

import divergencesplitter

EXPECTED_PUBLIC_API = (
    "Condition",
    "FrameSource",
    "LiveSplitConnection",
    "Rule",
    "Scenario",
)

RUNTIME_ONLY_PUBLIC_API = (
    "LiveSplitBridgeAdapter",
    "LiveSplitSnapshot",
    "LiveSplitUpdate",
    "LiveSplitUpdateKind",
    "TimerPhase",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", required=True, type=Path)
    args = parser.parse_args()

    for name in EXPECTED_PUBLIC_API:
        if not hasattr(divergencesplitter, name):
            raise RuntimeError(f"core public API is missing {name!r}")
    for name in RUNTIME_ONLY_PUBLIC_API:
        if hasattr(divergencesplitter, name):
            raise RuntimeError(f"core public API includes runtime-only {name!r}")

    if util.find_spec("divergencesplitter_runtime") is not None:
        raise RuntimeError("the core installation includes the runtime module")

    requirements = metadata.requires("divergencesplitter") or ()
    forbidden_dependencies = (
        "divergencesplitter-runtime",
        "divergencesplitter_runtime",
        "livesplit-bridge-client",
        "protobuf",
        "pyzmq",
    )
    forbidden = tuple(
        requirement
        for requirement in requirements
        if requirement.lower().startswith(forbidden_dependencies)
    )
    if forbidden:
        raise RuntimeError(
            f"the core distribution has runtime dependencies: {forbidden!r}"
        )

    files = metadata.files("divergencesplitter") or ()
    included_tests = tuple(
        str(file) for file in files if "tests" in PurePosixPath(str(file)).parts
    )
    if included_tests:
        raise RuntimeError(
            f"the core distribution includes test files: {included_tests!r}"
        )

    _verify_archives(args.artifacts)


def _verify_archives(directory: Path) -> None:
    wheels = tuple(directory.glob("*.whl"))
    source_distributions = tuple(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(source_distributions) != 1:
        raise RuntimeError("expected one core wheel and one core source distribution")

    with zipfile.ZipFile(wheels[0]) as archive:
        _verify_no_tests(wheels[0], archive.namelist())
    with tarfile.open(source_distributions[0], "r:gz") as archive:
        _verify_no_tests(source_distributions[0], archive.getnames())


def _verify_no_tests(archive: Path, names: list[str]) -> None:
    included_tests = tuple(
        name for name in names if "tests" in PurePosixPath(name).parts
    )
    if included_tests:
        raise RuntimeError(f"{archive.name} includes test files: {included_tests!r}")


if __name__ == "__main__":
    main()
