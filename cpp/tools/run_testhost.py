"""Run the optional DivergenceSplitter TestHost integration test.

The TestHost exits when its standard input closes, so this helper keeps the
stdin pipe open while it waits for READY and runs the C++ test executable.
"""

from __future__ import annotations

import argparse
import os
import queue
import subprocess
import sys
import threading
import time


def _read_output(process: subprocess.Popen[str], output: queue.Queue[str]) -> None:
    assert process.stdout is not None
    for line in process.stdout:
        output.put(line)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--testhost", required=True)
    parser.add_argument("--test-exe", required=True)
    parser.add_argument("--port", type=int, default=54000)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    if not os.path.isfile(args.testhost):
        print(f"TestHost not found: {args.testhost}", file=sys.stderr)
        return 2
    if not os.path.isfile(args.test_exe):
        print(f"test executable not found: {args.test_exe}", file=sys.stderr)
        return 2

    environment = os.environ.copy()
    environment["DIVERGENCESPLITTER_TESTHOST_PORT"] = str(args.port)
    environment["DIVERGENCESPLITTER_TESTHOST_ALLOW_CONTROL"] = "1"

    process = subprocess.Popen(
        [args.testhost, "--port", str(args.port)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    output: queue.Queue[str] = queue.Queue()
    reader = threading.Thread(
        target=_read_output,
        args=(process, output),
        daemon=True,
    )
    reader.start()

    ready = False
    deadline = time.monotonic() + args.timeout
    try:
        while time.monotonic() < deadline:
            try:
                line = output.get(timeout=0.5)
            except queue.Empty:
                if process.poll() is not None:
                    break
                continue
            print(line, end="", flush=True)
            if "READY" in line:
                ready = True
                break
        if not ready:
            print("TestHost did not report READY", file=sys.stderr)
            return 2

        completed = subprocess.run(
            [args.test_exe],
            cwd=os.path.dirname(os.path.abspath(args.test_exe)),
            env=environment,
            check=False,
        )
        return completed.returncode
    finally:
        try:
            if process.stdin is not None:
                process.stdin.write("\n")
                process.stdin.flush()
                process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
