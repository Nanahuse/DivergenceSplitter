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
    "Rule",
    "Scenario",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", required=True, type=Path)
    args = parser.parse_args()

    for name in EXPECTED_PUBLIC_API:
        if not hasattr(divergencesplitter, name):
            raise RuntimeError(f"core public API is missing {name!r}")

    if util.find_spec("divergencesplitter_runtime") is not None:
        raise RuntimeError("the core installation includes the runtime module")

    requirements = metadata.requires("divergencesplitter") or ()
    if any(
        requirement.lower().startswith(
            ("divergencesplitter-runtime", "divergencesplitter_runtime")
        )
        for requirement in requirements
    ):
        raise RuntimeError("the core distribution depends on the runtime distribution")

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
