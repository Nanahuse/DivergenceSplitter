"""Regression checks for download validation and distribution boundaries."""

import hashlib
import io
import json
import subprocess
import sys
import tempfile
import traceback
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
                self.assertRaises(RuntimeError) as caught,
            ):
                get_ndi_sdk.download(secret, destination)
            self.assertFalse(destination.exists())
            self.assertNotIn(secret, str(caught.exception))
            self.assertNotIn(secret, output.getvalue())

    def test_process_errors_remove_partial_file_and_hide_secret_arguments(self):
        secret = "https://secret.test/token"
        for error in (
            OSError(secret),
            subprocess.TimeoutExpired(["downloader", secret], 1),
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
                self.assertNotIn(secret, "".join(traceback.format_exception(caught.exception)))

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
            requests.append(self.path)
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
                f"http://127.0.0.1:{server.server_port}/sdk?secret=hidden&files=[1]",
                requests,
                payload,
            )
        finally:
            server.shutdown()
            thread.join(timeout=5)


@unittest.skipUnless(sys.platform == "win32", "Windows SDK downloader")
class DownloadRetryTests(unittest.TestCase):
    def test_transient_http_failures_recover_and_preserve_the_signed_query(self):
        for statuses in ([503, 503, 200], [429, 200]):
            with (
                self.subTest(statuses=statuses),
                tempfile.TemporaryDirectory() as temporary,
                download_server(statuses) as (url, requests, payload),
            ):
                destination = Path(temporary) / "sdk.exe"
                get_ndi_sdk.download(url, destination)
                self.assertEqual(destination.read_bytes(), payload)
                self.assertEqual(set(requests), {"/sdk?secret=hidden&files=[1]"})

    def test_persistent_http_failure_leaves_no_download(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            download_server([503]) as (url, requests, _),
        ):
            destination = Path(temporary) / "sdk.exe"
            with self.assertRaises(RuntimeError) as caught:
                get_ndi_sdk.download(url, destination)
            self.assertGreater(len(requests), 1)
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
                with self.assertRaises(RuntimeError):
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
                root / name for name in ("x64-windows/share", "bridge", "out", "cache")
            ]
            ports = ("boost-beast", "opencv4", "ryml", "c4core", "nlohmann-json", "zlib", "libpng")
            for port in ports:
                (share / port).mkdir(parents=True)
                (share / port / "copyright").write_text(port, encoding="utf-8")
            status = root / "vcpkg/status"
            status.parent.mkdir()
            status.write_text(
                "\n\n".join(
                    f"Package: {port}\nArchitecture: x64-windows\nStatus: install ok installed"
                    for port in ports
                )
                + "\n\nPackage: opencv4\nFeature: png\nDepends: libpng, zlib"
                + "\nArchitecture: x64-windows\nStatus: install ok installed\n",
                encoding="utf-8",
            )
            frontend = root / "frontend"
            for name in ("react", "react-dom", "scheduler"):
                package = frontend / "node_modules" / name
                package.mkdir(parents=True)
                (package / "LICENSE").write_text(f"{name} upstream", encoding="utf-8")
            bridge.mkdir()
            (bridge / "LICENSE").write_text("bridge upstream", encoding="utf-8")
            camera = root / "camera"
            camera.write_text("camera upstream", encoding="utf-8")
            imgui = root / "imgui"
            imgui.mkdir()
            (imgui / "LICENSE.txt").write_text("imgui upstream", encoding="utf-8")
            implot = root / "implot"
            implot.mkdir()
            (implot / "LICENSE").write_text("implot upstream", encoding="utf-8")
            with patch.object(collect_licenses, "pinned_file", return_value=camera):
                collect_licenses.collect(output, share, bridge, imgui, cache, implot, frontend=frontend)
            self.assertEqual((output / "opencv.txt").read_text(), "opencv4")
            self.assertEqual((output / "ryml.txt").read_text(), "ryml")
            self.assertEqual((output / "c4core.txt").read_text(), "c4core")
            self.assertEqual((output / "vcpkg/zlib.txt").read_text(), "zlib")
            self.assertEqual((output / "imgui.txt").read_text(), "imgui upstream")
            self.assertEqual((output / "implot.txt").read_text(), "implot upstream")
            self.assertEqual((output / "react-dom.txt").read_text(), "react-dom upstream")
            standalone = root / "standalone"
            builder_args = {"distribution": "scenario-builder", "frontend": frontend}
            collect_licenses.collect(standalone, share, None, None, cache, **builder_args)
            self.assertEqual((standalone / "webview2.txt").read_bytes(),
                             (output / "webview2.txt").read_bytes())
            self.assertEqual((standalone / "scheduler.txt").read_text(), "scheduler upstream")
            self.assertEqual((standalone / "vcpkg/libpng.txt").read_text(), "libpng")
            self.assertFalse((standalone / "imgui.txt").exists())
            self.assertFalse((standalone / "vcpkg/boost-beast.txt").exists())
            for port in ("opencv4", "ryml", "c4core", "libpng"):
                notice = share / port / "copyright"
                notice.unlink()
                with self.subTest(port=port), self.assertRaisesRegex(
                    RuntimeError, "Required dependency notice missing"
                ):
                    collect_licenses.collect(standalone, share, None, None, cache, **builder_args)
                notice.write_text(port, encoding="utf-8")


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        names = [
            "DivergenceSplitter.exe",
            "ScenarioBuilder.exe",
            "frontend/app.js",
            "plugins/decoder.dll",
            "plugins/alternate/decoder.dll",
            "LICENSE.txt",
            "DISTRIBUTION-NOTICE.txt",
            "licenses/ndi-headers.txt",
            "licenses/NDI-TERMS.txt",
        ]
        names += [
            f"licenses/{name}.txt"
            for name in (
                "imgui",
                "implot",
                "opencv",
                "boost",
                "ryml",
                "c4core",
                "nlohmann-json",
                "livesplit-bridge-client-cpp",
                "windows-capture-device-list",
                "webview2",
                "react",
                "react-dom",
                "scheduler",
            )
        ]
        self.ports = ["opencv4", "ryml", "c4core", "nlohmann-json", "zlib", "libpng"]
        names += [f"licenses/vcpkg/{port}.txt" for port in [*self.ports, "boost-beast"]]
        for name in names:
            file = self.root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"test")
        self.write_inventory("combined", [*self.ports, "boost-beast"])
        self.lock = {
            "installer_sha256": hashlib.sha256(b"installer").hexdigest(),
            "runtime_sha256": hashlib.sha256(b"runtime").hexdigest(),
            "runtime_licenses_sha256": hashlib.sha256(b"notices").hexdigest(),
            "agreement_sha256": hashlib.sha256(b"agreement").hexdigest(),
        }

    def write_inventory(self, distribution, ports):
        inventory = collect_licenses.distribution_inventory(distribution)
        inventory["vcpkg_notices"] = ports
        (self.root / "licenses/components.json").write_text(json.dumps(inventory), encoding="utf-8")

    def test_yaml_dependency_notices_are_required(self):
        for name in ("ryml", "c4core"):
            notice = self.root / f"licenses/{name}.txt"
            for contents in (None, b""):
                if contents is None:
                    notice.unlink()
                else:
                    notice.write_bytes(contents)
                with self.subTest(name=name, contents=contents), self.assertRaisesRegex(
                    RuntimeError, f"licenses/{name}"
                ):
                    verify_windows_zip.verify_contents(self.root, self.lock)
            notice.write_bytes(b"test")

    def test_duplicate_archive_entries_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "duplicate entries"):
            verify_windows_zip.verify_archive_names(
                ["ScenarioBuilder.exe", "scenariobuilder.exe"]
            )

    def test_accepts_package_with_notices_and_nested_application_files(self):
        verify_windows_zip.verify_archive_names([
            file.relative_to(self.root).as_posix()
            for file in self.root.rglob("*") if file.is_file()
        ])
        verify_windows_zip.verify_contents(self.root, self.lock)

    def test_bundled_webview2_runtime_is_rejected(self):
        runtime = self.root / "browser/123/msedgewebview2.exe"
        runtime.parent.mkdir(parents=True)
        runtime.write_bytes(b"webview runtime")
        with self.assertRaisesRegex(RuntimeError, "WebView2 Runtime"):
            verify_windows_zip.verify_contents(self.root, self.lock)

    def test_separately_distributed_ndi_files_are_rejected_even_in_subdirectories(self):
        directory = self.root / "extras"
        directory.mkdir()
        for name, contents in (
            ("Processing.NDI.Lib.x64.dll", b"other version"),
            ("Processing.NDI.Lib.Licenses.txt", b"other version"),
            ("NDI SDK License Agreement.pdf", b"different"),
            ("NDI SDK.exe", b"other version"),
            ("renamed.bin", b"agreement"),
            ("renamed.dll", b"runtime"),
            ("renamed.txt", b"notices"),
            ("renamed.exe", b"installer"),
        ):
            file = directory / name
            file.write_bytes(contents)
            with self.subTest(name=name), self.assertRaisesRegex(
                RuntimeError, "separately distributed NDI file"
            ):
                verify_windows_zip.verify_contents(self.root, self.lock)
            file.unlink()

    def test_empty_license_notice_is_rejected(self):
        file = self.root / "licenses/opencv.txt"
        for contents in (b"", b" \r\n"):
            file.write_bytes(contents)
            with self.subTest(contents=contents), self.assertRaisesRegex(RuntimeError, "missing or empty"):
                verify_windows_zip.verify_contents(self.root, self.lock)

    def test_transitive_license_notice_is_required(self):
        file = self.root / "licenses/vcpkg/zlib.txt"
        file.unlink()
        with self.assertRaisesRegex(RuntimeError, "transitive vcpkg"):
            verify_windows_zip.verify_contents(self.root, self.lock)

    def test_builder_accepts_its_own_notices_and_requires_each_dependency_license(self):
        self.write_inventory("scenario-builder", self.ports)
        for name in ("imgui.txt", "implot.txt", "boost.txt", "ndi-headers.txt", "NDI-TERMS.txt"):
            (self.root / "licenses" / name).unlink()
        verify_windows_zip.verify_contents(self.root, self.lock, builder_only=True)

        for name in ("ryml.txt", "webview2.txt", "react-dom.txt", "vcpkg/libpng.txt"):
            notice = self.root / "licenses" / name
            for contents in (None, b""):
                if contents is None:
                    notice.unlink()
                else:
                    notice.write_bytes(contents)
                with self.subTest(name=name, contents=contents), self.assertRaisesRegex(
                    RuntimeError, "notice"
                ):
                    verify_windows_zip.verify_contents(self.root, self.lock, builder_only=True)
            notice.write_bytes(b"test")

    def test_builder_rejects_an_inventory_for_the_combined_zip(self):
        with self.assertRaisesRegex(RuntimeError, "incorrect license inventory"):
            verify_windows_zip.verify_contents(self.root, self.lock, builder_only=True)

    def test_development_files_are_rejected_in_both_zip_formats(self):
        for builder_only in (False, True):
            if builder_only:
                self.write_inventory("scenario-builder", self.ports)
            for name in (
                "include/Processing.NDI.Lib.H",
                "include/ndi.hpp",
                "lib/Processing.NDI.Lib.x64.lib",
                "nested/NODE.EXE",
                "nested/npm.cmd",
                "frontend/Node_Modules/react/index.js",
            ):
                with (
                    self.subTest(builder_only=builder_only, name=name),
                    tempfile.TemporaryDirectory(dir=self.root) as temporary,
                ):
                    file = Path(temporary) / name
                    file.parent.mkdir(parents=True)
                    file.write_bytes(b"development file")
                    with self.assertRaisesRegex(RuntimeError, "development"):
                        verify_windows_zip.verify_contents(self.root, self.lock, builder_only=builder_only)


if __name__ == "__main__":
    unittest.main()
