"""Publish the Windows ZIP verified by the CI run for main."""

import argparse
import os
import re
import subprocess
from pathlib import Path


def capture(*command: str) -> str:
    return subprocess.run(
        command, check=True, stdout=subprocess.PIPE, text=True, encoding="utf-8"
    ).stdout.strip()


def eligible(repository: str, commit: str, tag: str) -> bool:
    releases = capture(
        "gh",
        "api",
        f"repos/{repository}/releases?per_page=100",
        "--paginate",
        "--jq",
        f'.[] | select(.tag_name == "{tag}") | .draft',
    ).splitlines()
    if "false" in releases:
        print(f"Skipping {tag}: release already published")
        return False

    tag_ref = f"refs/tags/{tag}"
    peeled_ref = f"{tag_ref}^{{}}"
    refs = {}
    output = capture("git", "ls-remote", "origin", "refs/heads/main", tag_ref, peeled_ref)
    for line in output.splitlines():
        sha, ref = line.split("\t", 1)
        refs[ref] = sha
    main = refs.get("refs/heads/main")
    if not main:
        raise RuntimeError("Cannot determine the current main commit")
    if commit != main:
        print(f"Skipping {tag}: main has advanced to {main}")
        return False

    # The peeled ref is the commit when the existing tag is annotated.
    target = refs.get(peeled_ref, refs.get(tag_ref))
    if target and target != commit:
        raise RuntimeError(f"{tag} points to {target}, expected {commit}")
    if "true" in releases:
        raise RuntimeError(f"A draft release for {tag} already exists")
    return True


def publish(repository: str, commit: str, tag: str, asset: Path) -> None:
    if not asset.is_file() or not asset.stat().st_size:
        raise RuntimeError(f"Missing or empty verified distribution: {asset}")
    if eligible(repository, commit, tag):
        subprocess.run(
            [
                "gh", "release", "create", tag, str(asset),
                "--repo", repository, "--target", commit, "--generate-notes",
            ],
            check=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("check", "publish"))
    args = parser.parse_args()
    repository = os.environ["GITHUB_REPOSITORY"]
    commit = os.environ["GITHUB_SHA"]
    version = os.environ["RELEASE_VERSION"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?", version):
        raise RuntimeError(f"Unexpected distribution version: {version!r}")
    tag = f"v{version}"

    if args.step == "check":
        if eligible(repository, commit, tag):
            if not re.fullmatch(r"[1-9][0-9]*", os.environ["RELEASE_ARTIFACT_ID"]):
                raise RuntimeError("Missing or invalid verified distribution artifact ID")
            with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
                output.write("publish=true\n")
    else:
        asset = Path("release-assets") / f"DivergenceSplitter-{version}-windows-x64.zip"
        publish(repository, commit, tag, asset)


if __name__ == "__main__":
    main()
