"""Test release outcomes against a local model of GitHub and its refs."""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publish_release


REPO = "owner/repo"
COMMIT = "a" * 40
OTHER_COMMIT = "b" * 40
TAG = "v0.2.0"
TAG_REF = f"refs/tags/{TAG}"
ASSET_NAME = "DivergenceSplitter-0.2.0-windows-x64.zip"
ASSET_CONTENTS = b"verified ZIP"


class FakeReleaseRemote:
    def __init__(self):
        self.refs = {"refs/heads/main": COMMIT}
        self.drafts = set()
        self.published = []
        self.unavailable = False

    def run(self, command, *, check, **options):
        executable, operation, *args = command
        output = ""
        if (executable, operation) == ("gh", "api"):
            if self.unavailable:
                raise subprocess.CalledProcessError(1, command)
            if TAG in self.drafts:
                output = "true"
            if any(tag == TAG for tag, *_ in self.published):
                output = "false"
        elif (executable, operation) == ("git", "ls-remote"):
            output = "\n".join(f"{sha}\t{ref}" for ref, sha in self.refs.items())
        elif (executable, operation, args[0]) == ("gh", "release", "create"):
            tag, asset, *flags = args[1:]
            target = flags[flags.index("--target") + 1]
            repository = flags[flags.index("--repo") + 1]
            commit = self.refs.get(f"refs/tags/{tag}^{{}}", self.refs.get(f"refs/tags/{tag}", target))
            self.published.append((tag, repository, commit, Path(asset).read_bytes()))
        else:
            raise AssertionError(f"Unexpected remote operation: {command}")
        return subprocess.CompletedProcess(command, 0, stdout=output)


class PublishReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.asset = Path(temporary) / ASSET_NAME
        self.remote = FakeReleaseRemote()
        self.enterContext(patch.object(publish_release.subprocess, "run", side_effect=self.remote.run))
        self.enterContext(redirect_stdout(io.StringIO()))

    def publish(self):
        publish_release.publish(REPO, COMMIT, TAG, self.asset)

    def test_rerun_leaves_one_release_with_the_verified_asset(self):
        self.asset.write_bytes(ASSET_CONTENTS)

        self.publish()
        self.publish()

        self.assertEqual(self.remote.published, [(TAG, REPO, COMMIT, ASSET_CONTENTS)])

    def test_lightweight_and_annotated_tags_on_target_commit_can_be_released(self):
        self.asset.write_bytes(ASSET_CONTENTS)
        for refs in ({TAG_REF: COMMIT}, {TAG_REF: OTHER_COMMIT, f"{TAG_REF}^{{}}": COMMIT}):
            with self.subTest(refs=refs):
                self.remote.refs.update(refs)
                self.remote.published.clear()

                self.publish()

                self.assertEqual(self.remote.published, [(TAG, REPO, COMMIT, ASSET_CONTENTS)])

    def test_tag_on_other_commit_fails(self):
        self.asset.write_bytes(ASSET_CONTENTS)
        self.remote.refs[TAG_REF] = OTHER_COMMIT

        with self.assertRaisesRegex(RuntimeError, "points to"):
            self.publish()

        self.assertEqual(self.remote.published, [])

    def test_existing_draft_blocks_publication(self):
        self.asset.write_bytes(ASSET_CONTENTS)
        self.remote.drafts.add(TAG)

        with self.assertRaisesRegex(RuntimeError, "draft release"):
            self.publish()

        self.assertEqual(self.remote.published, [])

    def test_main_advances_between_check_and_publish(self):
        self.asset.write_bytes(ASSET_CONTENTS)
        self.assertTrue(publish_release.eligible(REPO, COMMIT, TAG))
        self.remote.refs["refs/heads/main"] = OTHER_COMMIT

        self.publish()

        self.assertEqual(self.remote.published, [])

    def test_missing_or_empty_zip_fails(self):
        for file_exists in (False, True):
            with self.subTest(file_exists=file_exists):
                if file_exists:
                    self.asset.touch()
                with self.assertRaisesRegex(RuntimeError, "Missing or empty"):
                    self.publish()
                self.assertEqual(self.remote.published, [])

    def test_check_requires_a_single_artifact_id(self):
        output = self.asset.with_name("output.txt")
        environment = {
            "GITHUB_REPOSITORY": REPO,
            "GITHUB_SHA": COMMIT,
            "GITHUB_OUTPUT": str(output),
            "RELEASE_VERSION": "0.2.0",
            "RELEASE_ARTIFACT_ID": "",
        }
        with (
            patch.dict(os.environ, environment),
            patch.object(sys, "argv", ["publish_release.py", "check"]),
        ):
            for invalid in ("", "0", "123,456"):
                with self.subTest(artifact_id=invalid):
                    os.environ["RELEASE_ARTIFACT_ID"] = invalid
                    with self.assertRaisesRegex(RuntimeError, "artifact ID"):
                        publish_release.main()
                    self.assertFalse(output.exists())

            os.environ["RELEASE_ARTIFACT_ID"] = "123"
            publish_release.main()
            self.assertEqual(output.read_text(encoding="utf-8"), "publish=true\n")

    def test_remote_lookup_error_fails(self):
        self.asset.write_bytes(ASSET_CONTENTS)
        self.remote.unavailable = True

        with self.assertRaises(subprocess.CalledProcessError):
            self.publish()

        self.assertEqual(self.remote.published, [])
