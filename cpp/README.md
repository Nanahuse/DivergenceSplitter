# DivergenceSplitter C++23

This directory contains the C++23 product implementation of DivergenceSplitter.
It replaces the Python runtime and Flet UI with a native Windows application:

- Qt Widgets UI (Monitor, Diagnostics, Profile, Settings, About)
- OpenCV 4 frame sources and detectors
- declarative YAML scenarios through yaml-cpp
- LiveSplit.Bridge integration through
  [livesplit-bridge-client-cpp](https://github.com/Nanahuse/livesplit-bridge-client-cpp)
  pinned to `v0.1.0`
- CMake + Ninja + vcpkg manifest, GoogleTest + CTest

The Python packages in the repository are kept only as a migration reference
until the C++ product reaches feature parity. The C++ application never executes
Python scenario modules.

## Build

Prerequisites:

- Visual Studio 2022/2026 with the C++ desktop workload
- CMake 3.25+
- Ninja
- vcpkg (`VCPKG_ROOT` set)

From a Developer PowerShell:

```powershell
cd cpp
cmake --preset full
cmake --build --preset full --parallel
ctest --preset full --output-on-failure
```

`full` installs the Qt UI dependencies through vcpkg and can take a while on
the first build. For runtime/core work without Qt:

```powershell
cmake --preset core
cmake --build --preset core --parallel
ctest --preset core --output-on-failure
```

If a local `livesplit-bridge-client-cpp` checkout should be used instead of
FetchContent, pass:

```powershell
-D FETCHCONTENT_SOURCE_DIR_LIVESPLIT_BRIDGE=C:/path/to/livesplit-bridge-client-cpp
```

The bridge tag is controlled by `DIVERGENCESPLITTER_BRIDGE_TAG` (default
`v0.1.0`).

## Run

The headless runner is useful for checking configuration and input:

```powershell
build/full/divergencesplitter-cli.exe --profile C:\path\to\profile.json --check
build/full/divergencesplitter-cli.exe --profile C:\path\to\profile.json --seconds 10
```

The GUI executable is `build/full/DivergenceSplitter.exe`.

## Configuration

Profiles keep the existing JSON version 2 shape: one input source plus one or
more LiveSplit Bridge ports and YAML scenario paths. Version 1 profiles are
migrated by discarding the old ZeroMQ endpoints and assigning ports from 54000.

```json
{
  "version": 2,
  "source": {
    "type": "video",
    "path": "C:/videos/run.mp4",
    "transform": { "crop": null, "resize": null }
  },
  "instances": [
    {
      "connection": { "port": 54000 },
      "scenario": "C:/scenarios/run.yaml"
    }
  ]
}
```

Source types:

- `camera` with backend/device name, index for duplicate names, and an exact
  enumerated mode (width, height, fps, subtype GUID). The UI can enumerate
  devices with DirectShow and Media Foundation and keeps the configured
  identifiers when saving.
- `video` with an absolute local file path
- `ndi` with the advertised source name

Scenarios use the existing declarative YAML format. Supported condition types
are `detected`, `all`, `any`, `not`, `rising_edge`, `falling_edge`, `once`,
`elapsed`, `hold`, `nth`, `reset_when`, and `then`. Supported detectors are
`template_match`, `mean_absolute_similarity`,
`root_mean_square_similarity`, `difference_hash_similarity`,
`mean_brightness`, `color_range`, and `phase_correlation`.

See `examples/minimal-scenario.yaml`. Unknown fields, unsupported types, and
`.py` scenario files are rejected with a configuration error.

## Runtime behavior

- Capture runs on its own thread and publishes the newest normalized frame.
  Stale frames are replaced rather than queued.
- Every scenario instance evaluates on its own thread with its own state.
- Frames are shared with a lifetime-safe `shared_ptr`; equivalent detectors and
  grayscale preprocessing can share one per-frame cache.
- Control RPCs use the bridge client's async APIs from the instance thread, not
  the UI or capture thread.
- `control_result_unknown` is not retried automatically. The instance drops its
  scenario state, waits for the client to resynchronize, and suppresses the same
  action until the authoritative state changes.
- A growing `dropped_event_count()` triggers a query resynchronization.
- Manual Reset is queued to the instance thread and uses the current snapshot.
- Reset All in the Monitor page requires a two-second hold and cancels on
  release or pointer leave.

## Tests

`ctest --preset full` runs detector, condition, camera resolution, scenario
runtime, YAML loader, profile, frame cache, capture normalizer, instance
runtime, and Qt widget tests. The instance runtime tests use a fake bridge and
verify:

- Start/Split/Reset dispatch
- manual Reset on the instance thread
- no automatic resend after an unknown control result
- timer Events update the snapshot without a full Query synchronization
- reconnect/resynchronize

An optional real TestHost smoke test can be built with:

```powershell
cmake --preset full -DDIVERGENCESPLITTER_BUILD_TESTHOST_TESTS=ON
```

and run with `DIVERGENCESPLITTER_TESTHOST_PORT=54000`. Set
`DIVERGENCESPLITTER_TESTHOST_ALLOW_CONTROL=1` to include pause/resume control.

## Distribution

Release packaging:

```powershell
cmake --preset full-release
cmake --build --preset full-release --parallel
cmake --build build/full-release --target package
```

The ZIP contains the GUI, the headless CLI, Qt/OpenCV runtime DLLs and Qt
plugins, `LICENSE.txt`, `DISTRIBUTION-NOTICE.txt`, and third-party notices under
`licenses/`.

## NDI status

NDI remains an input option in the Profile schema and UI, but the SDK adapter is
not included in this migration. The NDI SDK is not shipped in this repository
or distribution. Selecting NDI and pressing Apply reports a clear configuration error; it never
silently falls back to camera or video. The SDK/runtime licensing review and the
adapter are tracked as the remaining NDI phase.
