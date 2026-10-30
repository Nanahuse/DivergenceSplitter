"""Regression checks for download validation and distribution boundaries."""

import hashlib
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
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
        self.assertEqual(
            get_ndi_sdk.official_url("https://downloads.ndi.tv/SDK/NDI 6 SDK.exe"),
            "https://downloads.ndi.tv/SDK/NDI%206%20SDK.exe",
        )

    def test_download_uses_curl_default_user_agent_and_captures_output(self):
        secret = "https://downloads.ndi.tv/sdk?token=secret&files=[1]"
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "sdk.exe"
            output = io.StringIO()
            result = subprocess.CompletedProcess(
                [], 0, secret.encode(), secret.encode()
            )
            with (
                patch.object(get_ndi_sdk.subprocess, "run", return_value=result) as run,
                redirect_stdout(output),
                redirect_stderr(output),
            ):
                get_ndi_sdk.download(secret, destination)
            arguments = run.call_args.args[0]
            self.assertEqual(arguments[0], "curl.exe")
            self.assertEqual(arguments[-2:], ["--", secret])
            for flag in ("--fail", "--location", "--globoff", "--silent"):
                self.assertIn(flag, arguments)
            self.assertNotIn("--user-agent", arguments)
            self.assertNotIn("-A", arguments)
            for option, value in (
                ("--connect-timeout", "30"),
                ("--max-time", "600"),
                ("--retry", "2"),
                ("--retry-max-time", "900"),
            ):
                self.assertEqual(arguments[arguments.index(option) + 1], value)
            self.assertNotIn("--retry-all-errors", arguments)
            self.assertNotIn("--retry-connrefused", arguments)
            self.assertEqual(run.call_args.kwargs["timeout"], 1530)
            self.assertGreater(run.call_args.kwargs["timeout"], 900 + 600)
            self.assertTrue(run.call_args.kwargs["capture_output"])
            self.assertFalse(run.call_args.kwargs["check"])
            self.assertEqual(output.getvalue(), "")

    def test_http_failure_removes_partial_file_without_logging_curl_output(self):
        secret = "https://secret.test/token"
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "sdk.exe"
            destination.write_bytes(b"partial")
            result = subprocess.CompletedProcess(
                [], 22, secret.encode(), secret.encode()
            )
            output = io.StringIO()
            with (
                patch.object(get_ndi_sdk.subprocess, "run", return_value=result),
                redirect_stdout(output),
                redirect_stderr(output),
                self.assertRaisesRegex(RuntimeError, "curl exit 22") as caught,
            ):
                get_ndi_sdk.download(secret, destination)
            self.assertFalse(destination.exists())
            self.assertNotIn(secret, str(caught.exception))
            self.assertEqual(output.getvalue(), "")

    def test_process_errors_remove_partial_file_and_hide_secret_arguments(self):
        secret = "https://secret.test/token"
        for error in (
            OSError(secret),
            subprocess.TimeoutExpired(
                ["curl.exe", secret], get_ndi_sdk.DOWNLOAD_PROCESS_TIMEOUT
            ),
        ):
            with (
                self.subTest(error=type(error).__name__),
                tempfile.TemporaryDirectory() as temporary,
            ):
                destination = Path(temporary) / "sdk.exe"
                destination.write_bytes(b"partial")
                with (
                    patch.object(get_ndi_sdk.subprocess, "run", side_effect=error),
                    self.assertRaises(RuntimeError) as caught,
                ):
                    get_ndi_sdk.download(secret, destination)
                self.assertFalse(destination.exists())
                self.assertNotIn(secret, str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)

    def test_hash_rejects_modified_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / "notice.txt"
            file.write_bytes(b"modified")
            with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                get_ndi_sdk.verify_hash(file, hashlib.sha256(b"original").hexdigest())


@contextmanager
def download_server(statuses):
    requests = []
    payload = b"complete SDK download"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status = statuses[min(len(requests), len(statuses) - 1)]
            requests.append(self.headers.get("User-Agent"))
            body = payload if status == 200 else b"temporary failure"
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield (
                f"http://127.0.0.1:{server.server_port}/sdk?secret=hidden",
                requests,
                payload,
            )
        finally:
            server.shutdown()
            thread.join(timeout=5)


@unittest.skipUnless(shutil.which("curl.exe"), "Windows curl.exe required")
class CurlRetryTests(unittest.TestCase):
    def test_transient_http_failures_recover_with_default_user_agent(self):
        for statuses in ([503, 503, 200], [429, 200]):
            with (
                self.subTest(statuses=statuses),
                tempfile.TemporaryDirectory() as temporary,
                download_server(statuses) as (url, requests, payload),
            ):
                destination = Path(temporary) / "sdk.exe"
                get_ndi_sdk.download(url, destination)
                self.assertEqual(destination.read_bytes(), payload)
                self.assertEqual(len(requests), len(statuses))
                self.assertTrue(all(agent.startswith("curl/") for agent in requests))

    def test_retry_exhaustion_stops_after_three_attempts_and_removes_output(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            download_server([503]) as (url, requests, _),
        ):
            destination = Path(temporary) / "sdk.exe"
            with self.assertRaisesRegex(RuntimeError, "curl exit 22") as caught:
                get_ndi_sdk.download(url, destination)
            self.assertEqual(len(requests), 3)
            self.assertFalse(destination.exists())
            self.assertNotIn(url, str(caught.exception))

    def test_permanent_http_errors_are_not_retried(self):
        for status in (403, 404):
            with (
                self.subTest(status=status),
                tempfile.TemporaryDirectory() as temporary,
                download_server([status, 200]) as (url, requests, _),
            ):
                destination = Path(temporary) / "sdk.exe"
                with self.assertRaisesRegex(RuntimeError, "curl exit 22"):
                    get_ndi_sdk.download(url, destination)
                self.assertEqual(len(requests), 1)
                self.assertFalse(destination.exists())


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
