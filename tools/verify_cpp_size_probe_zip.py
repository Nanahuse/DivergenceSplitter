"""Launch the probe after extracting its ZIP into a separate directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from measure_distribution import extract_archive, sha256
from prepare_cpp_distribution import smoke


def verify(archive: Path, destination: Path, output: Path) -> None:
    extract_archive(archive, destination)
    root = destination / "distribution"
    smoke(root)
    output.write_text(
        json.dumps(
            {
                "result": "passed",
                "archive_sha256": sha256(archive),
                "executable": "distribution/bin/size-probe.exe",
                "ndi_status": (root / "ndi-status.txt")
                .read_text(encoding="utf-8")
                .strip(),
                "log": (root / "build-metadata/smoke-test.txt").read_text(
                    encoding="utf-8"
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("PASS: executable launched from extracted distribution ZIP")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--extract-to", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(args.archive, args.extract_to, args.output)


if __name__ == "__main__":
    main()
