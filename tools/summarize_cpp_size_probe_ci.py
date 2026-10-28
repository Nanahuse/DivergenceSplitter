"""Summarize measured CI sizes, local differences, timings and large files."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def summarize(
    ci_report: Path, local_report: Path, timings: Path, build_log: Path
) -> str:
    ci = json.loads(ci_report.read_text(encoding="utf-8"))
    local = json.loads(local_report.read_text(encoding="utf-8"))
    elapsed = json.loads(timings.read_text(encoding="utf-8-sig"))
    log = build_log.read_text(encoding="utf-8-sig", errors="replace")
    install = re.search(
        r"All requested installations completed successfully in: ([^\r\n]+)", log
    )
    restored = re.search(r"Restored (\d+) package", log)
    lines = [
        "# CI / local measurements",
        "",
        f"NDI: {ci['ndi_status']}",
        "",
        "These are minimal dependency-probe measurements; no complete-port estimate is made.",
        "",
        "| Measurement | Local bytes | CI bytes | CI - local bytes |",
        "| --- | ---: | ---: | ---: |",
    ]
    for key in ("unpacked_bytes", "zip_bytes"):
        lines.append(
            f"| {key} | {local[key]:,} | {ci[key]:,} | {ci[key] - local[key]:+,} |"
        )
    lines += [
        "",
        f"Local ZIP settings: `{json.dumps(local['zip_settings'], sort_keys=True)}`",
        f"CI ZIP settings: `{json.dumps(ci['zip_settings'], sort_keys=True)}`",
        "",
        "Compiler, SDK and runner differences are recorded in the distribution's build-metadata/toolchain.json.",
        "The ZIP bytes above refer to cpp.zip. The outer Actions Artifact is a separate transport archive, also containing reports and the legacy ZIP.",
        "",
        f"Binary cache hit: `{elapsed['binary_cache_hit']}`",
        f"vcpkg reported install duration: `{install.group(1) if install else 'see build.log'}`",
        f"Restored vcpkg binary packages: `{restored.group(1) if restored else 'see build.log'}`",
        "",
        "| Phase | Seconds |",
        "| --- | ---: |",
    ]
    for phase, seconds in elapsed["phases_seconds"].items():
        lines.append(f"| {phase} | {seconds:.2f} |")
    lines += [
        f"| total script time | {elapsed['total_seconds']:.2f} |",
        "",
        "Configure time includes dependency acquisition/build and CMake checks; the vcpkg duration above is reported separately.",
        "",
        "| Category | Local bytes | CI bytes | Difference |",
        "| --- | ---: | ---: | ---: |",
    ]
    for category in sorted(set(local["categories"]) | set(ci["categories"])):
        before, after = (
            local["categories"].get(category, 0),
            ci["categories"].get(category, 0),
        )
        lines.append(f"| {category} | {before:,} | {after:,} | {after - before:+,} |")
    lines += [
        "",
        "## Largest deployed files",
        "",
        "| Path | Bytes | Category |",
        "| --- | ---: | --- |",
    ]
    for item in sorted(ci["files"], key=lambda item: item["bytes"], reverse=True)[:20]:
        lines.append(f"| {item['path']} | {item['bytes']:,} | {item['category']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ci-report", required=True, type=Path)
    parser.add_argument("--local-report", required=True, type=Path)
    parser.add_argument("--timings", required=True, type=Path)
    parser.add_argument("--build-log", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.write_text(
        summarize(args.ci_report, args.local_report, args.timings, args.build_log),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
