"""Record process memory and CPU samples on Windows without modifying the process."""

from __future__ import annotations

import argparse
import csv
import ctypes as ct
from ctypes import wintypes as win
from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import time


class ProcessMemoryCounters(ct.Structure):
    _fields_ = [
        ("cb", win.DWORD),
        ("PageFaultCount", win.DWORD),
        ("PeakWorkingSetSize", ct.c_size_t),
        ("WorkingSetSize", ct.c_size_t),
        ("QuotaPeakPagedPoolUsage", ct.c_size_t),
        ("QuotaPagedPoolUsage", ct.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ct.c_size_t),
        ("QuotaNonPagedPoolUsage", ct.c_size_t),
        ("PagefileUsage", ct.c_size_t),
        ("PeakPagefileUsage", ct.c_size_t),
        ("PrivateUsage", ct.c_size_t),
    ]


class ProcessMemoryCountersEx2(ProcessMemoryCounters):
    _fields_ = [
        ("PrivateWorkingSetSize", ct.c_size_t),
        ("SharedCommitUsage", ct.c_ulonglong),
    ]


def filetime_ticks(value: win.FILETIME) -> int:
    return (value.dwHighDateTime << 32) | value.dwLowDateTime


def record(args: argparse.Namespace) -> None:
    kernel = ct.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (win.DWORD, win.BOOL, win.DWORD)
    kernel.OpenProcess.restype = win.HANDLE
    kernel.CloseHandle.argtypes = (win.HANDLE,)
    kernel.CloseHandle.restype = win.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = (
        win.HANDLE, win.DWORD, win.LPWSTR, ct.POINTER(win.DWORD)
    )
    kernel.QueryFullProcessImageNameW.restype = win.BOOL
    kernel.K32GetProcessMemoryInfo.argtypes = (win.HANDLE, ct.c_void_p, win.DWORD)
    kernel.K32GetProcessMemoryInfo.restype = win.BOOL
    kernel.GetProcessTimes.argtypes = (win.HANDLE,) + (ct.POINTER(win.FILETIME),) * 4
    kernel.GetProcessTimes.restype = win.BOOL
    kernel.WaitForSingleObject.argtypes = (win.HANDLE, win.DWORD)
    kernel.WaitForSingleObject.restype = win.DWORD

    query_limited_information = 0x1000
    synchronize = 0x00100000
    process = kernel.OpenProcess(query_limited_information | synchronize, False, args.pid)
    if not process:
        raise ct.WinError(ct.get_last_error())

    try:
        executable = ct.create_unicode_buffer(32768)
        size = win.DWORD(len(executable))
        if not kernel.QueryFullProcessImageNameW(process, 0, executable, ct.byref(size)):
            raise ct.WinError(ct.get_last_error())

        counters = ProcessMemoryCountersEx2()
        counters.cb = ct.sizeof(counters)
        if not kernel.K32GetProcessMemoryInfo(process, ct.byref(counters), counters.cb):
            error = ct.get_last_error()
            if error not in (24, 87):  # ERROR_BAD_LENGTH or ERROR_INVALID_PARAMETER
                raise ct.WinError(error)
            counters = ProcessMemoryCounters()
            counters.cb = ct.sizeof(counters)
        created, exited, system, user = (win.FILETIME() for _ in range(4))
        logical_cpus = os.cpu_count() or 1
        with args.output.open("x", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow((
                "utc", "pid", "executable", "windows_version", "logical_cpus", "build", "revision", "phase",
                "scheduled_s", "elapsed_s", "working_set_bytes", "private_bytes", "peak_working_set_bytes",
                "private_working_set_bytes", "process_cpu_seconds", "cpu_percent",
            ))
            stream.flush()
            started = time.monotonic()
            previous_time = previous_cpu = None
            for scheduled in args.at:
                while (remaining := started + scheduled - time.monotonic()) > 0:
                    milliseconds = min(0xFFFFFFFE, max(1, round(remaining * 1000)))
                    result = kernel.WaitForSingleObject(process, milliseconds)
                    if result == 0:
                        raise RuntimeError("target process exited before the next sample")
                    if result != 258:  # WAIT_TIMEOUT
                        raise ct.WinError(ct.get_last_error())
                if not kernel.K32GetProcessMemoryInfo(process, ct.byref(counters), counters.cb):
                    raise ct.WinError(ct.get_last_error())
                if not kernel.GetProcessTimes(process, *(ct.byref(t) for t in (created, exited, system, user))):
                    raise ct.WinError(ct.get_last_error())
                elapsed = time.monotonic() - started
                cpu = (filetime_ticks(system) + filetime_ticks(user)) / 10_000_000
                utilization = "" if previous_time is None else (
                    f"{100 * (cpu - previous_cpu) / (elapsed - previous_time) / logical_cpus:.3f}"
                )
                writer.writerow((
                    datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                    args.pid, executable.value, platform.version(), logical_cpus, args.build, args.revision,
                    args.phase, scheduled, f"{elapsed:.3f}", counters.WorkingSetSize, counters.PrivateUsage,
                    counters.PeakWorkingSetSize, getattr(counters, "PrivateWorkingSetSize", ""),
                    f"{cpu:.6f}", utilization,
                ))
                stream.flush()
                previous_time, previous_cpu = elapsed, cpu
    finally:
        kernel.CloseHandle(process)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--build", choices=("Debug", "Release", "RelWithDebInfo", "MinSizeRel"), required=True)
    parser.add_argument("--revision", required=True, help="revision of the running binary")
    parser.add_argument("--phase", required=True, help="label for the workload in this recording")
    parser.add_argument("--output", type=Path, required=True, help="new CSV file")
    parser.add_argument("--at", type=int, nargs="+", default=[0, 60, 300, 1800], metavar="SECONDS")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Windows is required")
    if not 0 < args.pid <= 0xFFFFFFFF:
        parser.error("--pid must be a positive Windows process ID")
    if min(args.at) < 0 or args.at != sorted(set(args.at)):
        parser.error("--at requires increasing, nonnegative times")
    try:
        record(args)
    except (OSError, RuntimeError) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
