"""Regression checks for download validation and distribution boundaries."""

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collect_licenses
import get_ndi_sdk
import verify_windows_zip


class SdkTests(unittest.TestCase):
    def test_official_https_only(self):
        for url in (
            "http://downloads.ndi.tv/sdk",
            "https://downloads.ndi.tv.evil.test/sdk",
            "https://evil.test/?secret=hidden",
            "https://[invalid",
        ):
            with (
                self.subTest(url=url),
                self.assertRaisesRegex(RuntimeError, "official HTTPS"),
            ):
                get_ndi_sdk.official_url(url)
        self.assertEqual(
            get_ndi_sdk.official_url(" https://downloads.ndi.tv/sdk "),
            "https://downloads.ndi.tv/sdk",
        )

    def test_request_error_does_not_expose_secret(self):
        with patch(
            "urllib.request.urlopen", side_effect=OSError("https://secret.test/token")
        ):
            with self.assertRaises(RuntimeError) as caught:
                get_ndi_sdk.download("https://secret.test/token", Path("unused"))
            self.assertNotIn("secret.test", str(caught.exception))
            self.assertTrue(caught.exception.__suppress_context__)

    def test_hash_rejects_modified_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / "notice.txt"
            file.write_bytes(b"modified")
            with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                get_ndi_sdk.verify_hash(file, hashlib.sha256(b"original").hexdigest())


class LicenseTests(unittest.TestCase):
    def test_corrupt_cache_is_not_packaged(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            pin = hashlib.sha256(b"original").hexdigest()
            (cache / pin).write_bytes(b"corrupted")
            entry = {
                "name": "notice",
                "sha256": pin,
                "url": "https://example.test/notice",
            }
            with patch("urllib.request.urlopen") as request:
                request.return_value.__enter__.return_value.read.return_value = (
                    b"changed upstream"
                )
                with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                    collect_licenses.pinned_file(entry, cache)

    def test_dependency_notices_come_from_build_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            share, bridge, output, cache = [
                root / name for name in ("share", "bridge", "out", "cache")
            ]
            for port in ("boost-asio", "opencv4", "yaml-cpp", "nlohmann-json", "zlib"):
                (share / port).mkdir(parents=True)
                (share / port / "copyright").write_text(port, encoding="utf-8")
            bridge.mkdir()
            (bridge / "LICENSE").write_text("bridge upstream", encoding="utf-8")
            camera = root / "camera"
            camera.write_text("camera upstream", encoding="utf-8")
            with patch.object(collect_licenses, "pinned_file", return_value=camera):
                collect_licenses.collect(output, share, bridge, None, "", cache)
            self.assertEqual((output / "opencv.txt").read_text(), "opencv4")
            self.assertEqual((output / "vcpkg/zlib.txt").read_text(), "zlib")
            (share / "opencv4/copyright").unlink()
            with self.assertRaisesRegex(
                RuntimeError, "Required dependency notice missing"
            ):
                collect_licenses.collect(output, share, bridge, None, "", cache)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        names = [
            "platforms/qwindows.dll",
            "Qt6Core.dll",
            "opencv_core4.dll",
            "vc_redist.x64.exe",
            "LICENSE.txt",
            "DISTRIBUTION-NOTICE.txt",
            "licenses/NDI-TERMS.txt",
        ]
        names += [
            f"licenses/{name}.txt"
            for name in (
                "qtbase",
                "opencv",
                "boost",
                "yaml-cpp",
                "nlohmann-json",
                "livesplit-bridge-client-cpp",
                "windows-capture-device-list",
            )
        ]
        for name in names:
            file = self.root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"test")
        self.lock = {
            "runtime_sha256": hashlib.sha256(b"runtime").hexdigest(),
            "runtime_licenses_sha256": hashlib.sha256(b"notices").hexdigest(),
            "agreement_sha256": hashlib.sha256(b"agreement").hexdigest(),
        }

    def test_ndi_files_and_notices_are_required_and_verified(self):
        (self.root / "Processing.NDI.Lib.x64.dll").write_bytes(b"runtime")
        (self.root / "Processing.NDI.Lib.Licenses.txt").write_bytes(b"notices")
        verify_windows_zip.verify_contents(self.root, True, self.lock)
        (self.root / "Processing.NDI.Lib.Licenses.txt").write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError, "modified NDI"):
            verify_windows_zip.verify_contents(self.root, True, self.lock)

    def test_contract_pdf_is_rejected_even_when_renamed(self):
        for name, contents in (
            ("NDI SDK License Agreement.pdf", b"different"),
            ("renamed.pdf", b"agreement"),
        ):
            file = self.root / name
            file.write_bytes(contents)
            with self.assertRaisesRegex(RuntimeError, "contract PDF"):
                verify_windows_zip.verify_contents(self.root, False, self.lock)
            file.unlink()

    def test_development_files_rejected(self):
        for name in ("Include.h", "library.lib", "NDI SDK.exe", "NDI Runtime.exe"):
            file = self.root / name
            file.write_bytes(b"test")
            with self.assertRaisesRegex(RuntimeError, "development files"):
                verify_windows_zip.verify_contents(self.root, False, self.lock)
            file.unlink()

    def test_off_package_rejects_runtime(self):
        verify_windows_zip.verify_contents(self.root, False, self.lock)
        (self.root / "Processing.NDI.Lib.x64.dll").write_bytes(b"runtime")
        with self.assertRaisesRegex(RuntimeError, "SDK-disabled"):
            verify_windows_zip.verify_contents(self.root, False, self.lock)


if __name__ == "__main__":
    unittest.main()
