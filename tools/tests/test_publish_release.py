"""Test release decisions without contacting GitHub."""

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
MAIN_REF = f"{COMMIT}\trefs/heads/main"
TAG_REF = f"refs/tags/{TAG}"
ASSET_NAME = "DivergenceSplitter-0.2.0-windows-x64.zip"


class PublishReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.asset = Path(temporary) / ASSET_NAME
        self.remote = self.enterContext(patch.object(publish_release, "capture"))
        self.create = self.enterContext(patch.object(publish_release.subprocess, "run"))
        self.enterContext(redirect_stdout(io.StringIO()))

    def publish(self):
        publish_release.publish(REPO, COMMIT, TAG, self.asset)

    def test_new_release_and_rerun(self):
        self.asset.write_bytes(b"test ZIP")
        self.remote.side_effect = ["", MAIN_REF, "false"]

        self.publish()
        self.publish()

        self.create.assert_called_once_with(
            [
                "gh", "release", "create", TAG, str(self.asset),
                "--repo", REPO, "--target", COMMIT, "--generate-notes",
            ],
            check=True,
        )

    def test_tag_on_target_commit_can_be_released(self):
        self.asset.write_bytes(b"test ZIP")
        for refs in (
            f"{COMMIT}\t{TAG_REF}",
            f"{OTHER_COMMIT}\t{TAG_REF}\n{COMMIT}\t{TAG_REF}^{{}}",
        ):
            with self.subTest(refs=refs):
                self.remote.side_effect = ["", f"{MAIN_REF}\n{refs}"]
                self.create.reset_mock()
                self.publish()
                self.create.assert_called_once()

    def test_tag_on_other_commit_fails(self):
        self.asset.write_bytes(b"test ZIP")
        self.remote.side_effect = ["", f"{MAIN_REF}\n{OTHER_COMMIT}\t{TAG_REF}"]

        with self.assertRaisesRegex(RuntimeError, "points to"):
            self.publish()

        self.create.assert_not_called()

    def test_existing_draft_blocks_publication(self):
        self.asset.write_bytes(b"test ZIP")
        self.remote.side_effect = ["true", MAIN_REF]

        with self.assertRaisesRegex(RuntimeError, "draft release"):
            self.publish()

        self.create.assert_not_called()

    def test_main_advances_between_check_and_publish(self):
        self.asset.write_bytes(b"test ZIP")
        self.remote.side_effect = ["", MAIN_REF, "", f"{OTHER_COMMIT}\trefs/heads/main"]

        self.assertTrue(publish_release.eligible(REPO, COMMIT, TAG))
        self.publish()

        self.create.assert_not_called()

    def test_missing_or_empty_zip_fails(self):
        for file_exists in (False, True):
            with self.subTest(file_exists=file_exists):
                if file_exists:
                    self.asset.touch()
                with self.assertRaisesRegex(RuntimeError, "Missing or empty"):
                    self.publish()

        self.remote.assert_not_called()
        self.create.assert_not_called()

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
            self.remote.side_effect = ["", MAIN_REF, "", MAIN_REF]
            with self.assertRaisesRegex(RuntimeError, "artifact ID"):
                publish_release.main()
            self.assertFalse(output.exists())

            os.environ["RELEASE_ARTIFACT_ID"] = "123"
            publish_release.main()
            self.assertEqual(output.read_text(encoding="utf-8"), "publish=true\n")

    def test_remote_lookup_error_fails(self):
        self.asset.write_bytes(b"test ZIP")
        self.remote.side_effect = [subprocess.CalledProcessError(1, "gh")]

        with self.assertRaises(subprocess.CalledProcessError):
            self.publish()

        self.create.assert_not_called()
