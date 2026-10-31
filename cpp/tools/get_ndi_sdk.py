"""Acquire the pinned official Windows SDK without logging its Secret URL."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import zipfile
from ctypes import wintypes
from pathlib import Path

DOWNLOAD_TRANSFER_TIMEOUT = 600
DOWNLOAD_RETRY_WINDOW = 900
# curl may start its final attempt just before the retry window expires.
# Allow that transfer to finish, plus 30 seconds for process startup/cleanup.
DOWNLOAD_PROCESS_TIMEOUT = DOWNLOAD_RETRY_WINDOW + DOWNLOAD_TRANSFER_TIMEOUT + 30


def verify_hash(path: Path, expected: str) -> None:
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise RuntimeError(f"SHA-256 mismatch: {path.name}")


def download(url: str, destination: Path) -> None:
    # Capture curl output: its errors can contain the Secret or redirect URLs.
    # Ignore curlrc so machine settings cannot override the default User-Agent.
    try:
        result = subprocess.run(
            [
                "curl.exe",
                "--disable",
                "--fail",
                "--location",
                "--silent",
                "--show-error",
                "--globoff",
                "--connect-timeout",
                "30",
                "--max-time",
                str(DOWNLOAD_TRANSFER_TIMEOUT),
                "--retry",
                "2",
                "--retry-max-time",
                str(DOWNLOAD_RETRY_WINDOW),
                "--output",
                str(destination),
                "--",
                url,
            ],
            capture_output=True,
            check=False,
            timeout=DOWNLOAD_PROCESS_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as error:
        destination.unlink(missing_ok=True)
        raise RuntimeError(
            f"Download failed (curl {type(error).__name__}; URL and output suppressed)"
        ) from None
    if result.returncode != 0:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"Download failed (curl exit {result.returncode})")


def official_url(value: str) -> str:
    try:
        url = urllib.parse.urlsplit(value.strip())
        valid = url.scheme == "https" and url.hostname == "downloads.ndi.tv"
    except ValueError:
        valid = False
    if not valid:
        raise RuntimeError("NDI SDK URL must use the official HTTPS distribution host")
    # .NET Uri previously escaped spaces; the HTTP client needs an encoded URL.
    path = urllib.parse.quote(url.path, safe="/%:@!$&'()*+,;=-._~")
    query = urllib.parse.quote(url.query, safe="%=&/:?@!$'()*+,;~-._")
    return urllib.parse.urlunsplit(url._replace(path=path, query=query))


def product_version(path: Path) -> str:
    """Read ProductVersion from Windows version resources, as the SDK pin does."""
    if sys.platform != "win32":
        raise RuntimeError("Windows version resources require Windows")
    version = ctypes.WinDLL("version", use_last_error=True)
    version.GetFileVersionInfoSizeW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    version.GetFileVersionInfoW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    version.VerQueryValueW.argtypes = [
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.UINT),
    ]
    size = version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        raise RuntimeError(f"Missing version resource: {path.name}")
    data = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, data):
        raise RuntimeError(f"Unreadable version resource: {path.name}")
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not version.VerQueryValueW(
        data, "\\VarFileInfo\\Translation", ctypes.byref(pointer), ctypes.byref(length)
    ):
        raise RuntimeError(f"Missing version translation: {path.name}")
    translation = ctypes.cast(pointer, ctypes.POINTER(wintypes.WORD))
    key = f"\\StringFileInfo\\{translation[0]:04x}{translation[1]:04x}\\ProductVersion"
    if not version.VerQueryValueW(
        data, key, ctypes.byref(pointer), ctypes.byref(length)
    ):
        raise RuntimeError(f"Missing product version: {path.name}")
    return ctypes.wstring_at(pointer, length.value).rstrip("\0").strip()


def verify_signature(path: Path) -> None:
    # The Windows SDK tool verifies the Authenticode chain and timestamp using
    # the OS trust policy. Capture its output rather than logging file details.
    tool = shutil.which("signtool.exe")
    if not tool:
        sdk_bin = os.environ.get("WindowsSdkVerBinPath", "")
        candidate = Path(sdk_bin) / "x64/signtool.exe"
        if sdk_bin and candidate.is_file():
            tool = str(candidate)
    if not tool:
        raise RuntimeError(
            "signtool.exe missing; initialize the Windows SDK/MSVC environment"
        )
    result = subprocess.run(
        [tool, "verify", "/pa", "/v", str(path)],
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    # /v reports the leaf publisher last, before the timestamp certificate chain.
    chain = result.stdout.split("Signing Certificate Chain:", 1)
    publishers = (
        re.findall(
            r"Issued to:\s*([^\r\n]+)",
            chain[1].split("The signature is timestamped:", 1)[0],
        )
        if len(chain) == 2
        else []
    )
    if result.returncode or not publishers or publishers[-1].strip() != "Vizrt AG":
        raise RuntimeError("NDI SDK installer signature is not valid for Vizrt AG")


def acquire(destination: Path) -> Path:
    lock = json.loads(
        Path(__file__).with_name("ndi-sdk-lock.json").read_text(encoding="utf-8")
    )
    value = os.environ.get("NDI_SDK_URL_WINDOWS")
    if not value:
        raise RuntimeError("Required NDI_SDK_URL_WINDOWS Secret is not configured")
    url = official_url(value)
    destination.mkdir(parents=True, exist_ok=True)
    installer = destination / "ndi-sdk.exe"
    try:
        download(url, installer)
        verify_hash(installer, lock["installer_sha256"])
        if product_version(installer) != lock["version"]:
            raise RuntimeError("NDI SDK installer product version differs from the pin")
        verify_signature(installer)
        archive = destination / "innoextract.zip"
        download(
            f"https://constexpr.org/innoextract/files/innoextract-{lock['innoextract_version']}-windows.zip",
            archive,
        )
        verify_hash(archive, lock["innoextract_sha256"])
        extractor = destination / "extractor"
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(extractor)
        subprocess.run(
            [
                str(extractor / "innoextract.exe"),
                str(installer),
                "--output-dir",
                str(destination),
                "--silent",
            ],
            check=True,
        )
        sdk = destination / "app"
        for header in ("Processing.NDI.Lib.h", "Processing.NDI.DynamicLoad.h"):
            if not (sdk / "Include" / header).is_file():
                raise RuntimeError(f"Extracted SDK missing Include/{header}")
        for name, pin in (
            ("Bin/x64/Processing.NDI.Lib.x64.dll", "runtime"),
            ("Bin/x64/Processing.NDI.Lib.Licenses.txt", "runtime_licenses"),
            ("NDI SDK License Agreement.pdf", "agreement"),
        ):
            verify_hash(sdk / name, lock[f"{pin}_sha256"])
        if (
            product_version(sdk / "Bin/x64/Processing.NDI.Lib.x64.dll")
            != lock["version"]
        ):
            raise RuntimeError("NDI runtime version differs from the pin")
        if os.environ.get("GITHUB_ENV"):
            with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as output:
                output.write(f"NDI_SDK_DIR={sdk}\n")
        print(
            f"Validated official NDI SDK {lock['version']} (hashes, versions, Authenticode)"
        )
        return sdk
    finally:
        installer.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path(os.environ.get("RUNNER_TEMP", ".")) / "ndi-sdk",
    )
    args = parser.parse_args()
    try:
        acquire(args.destination.resolve())
    except (
        RuntimeError,
        OSError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
    ) as error:
        print(f"NDI SDK acquisition failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
