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
- Python 3.10+ (distribution helpers; `Python3_EXECUTABLE` can select it)

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
  identifiers when saving. DirectShow FourCC modes are set and verified; modes
  whose subtype cannot be selected through OpenCV are rejected at Apply. Media
  Foundation verifies width/height/FPS, while its subtype is matched from
  enumeration but is not selectable through OpenCV; the UI labels these modes
  as `size/FPS`.
- `video` with an absolute local file path
- `ndi` with the advertised source name

Enable **Resize reference images** in Profile (JSON: `resize.resize_references`)
to resize scenario references using the selected interpolation. References without
an ROI use the resize output dimensions; references with an ROI use its width and
height, keeping the ROI coordinates unchanged. Capture crop margins do not apply
to references. Apply validates the transformed images before starting the runtime;
the YAML and image files are left unchanged. With resize disabled or
`resize_references: false` (the default), references keep their original size.

Scenarios use the existing declarative YAML format. Supported condition types
are `detected`, `all`, `any`, `not`, `rising_edge`, `falling_edge`, `once`,
`elapsed`, `hold`, `nth`, `reset_when`, and `then`. Supported detectors are
`template_match`, `mean_absolute_similarity`,
`root_mean_square_similarity`, `histogram_similarity`,
`perceptual_hash_similarity`, `difference_hash_similarity`,
`mean_brightness`, `color_range`, and `phase_correlation`.

See `examples/minimal-scenario.yaml`. Unknown fields, unsupported types, and
`.py` scenario files are rejected with a configuration error.

Histogram and perceptual hash similarity accept 8-bit BGR frames and BGR/BGRA
references with optional binary alpha masks. A masked reference must match the
frame (or ROI) dimensions; unmasked images may differ in size. Histogram similarity
uses 512 normalized color bins and Bhattacharyya distance. Perceptual hash
similarity matches the Python detector's 8x8 area resize followed by OpenCV 4.12.0
PHash (32x32 exact linear resize, grayscale, DCT, 64 bits). It uses Core/Imgproc
without adding opencv_contrib to the C++ dependencies.

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

Third-party license bodies are collected at package time from the installed
vcpkg dependencies and the fetched Bridge source. The camera adaptation's
upstream license and external Qt 6.8.3 license files are downloaded from pinned
upstream commits and checked against `tools/third-party-license-lock.json`.
Only their URLs and SHA-256 values are tracked in this repository; downloaded
texts stay in the ignored build directory. Packaging fails if required notices
are missing or a downloaded notice differs from its pin. Transitive dependency
notices are also included under `licenses/vcpkg/`. The application-authored
NDI notices and `NDI-TERMS.txt` remain part of the source tree.

## NDI® input and Windows redistribution

NDI® is a registered trademark of Vizrt NDI AB. [NDI website](https://ndi.video/).

The official Windows ZIP includes the NDI 6.3.2.0 runtime next to the executable.
Unzip the complete archive and run `DivergenceSplitter.exe`; a separate NDI SDK
or runtime installation is unnecessary. In Profile, choose NDI, use Search again,
select a sender and Apply. The editable list preserves saved names when senders
are offline and refreshes while the page is visible. Discovery runs outside the
GUI thread. Profiles continue to store `source.type: "ndi"` and `source.name`.
Crop, Resize and `resize_references` use the same pipeline as Camera / Video.

Receiver reads wait at most 50 ms. An ordinary timeout, status change or paused
sender keeps the receiver alive; the SDK reconnects when that source returns.
Fatal SDK / format errors stop capture and appear in diagnostics. The receiver
requests deinterlaced BGRX/BGRA; conversion also supports UYVY/UYVA and RGBA/RGBX,
respects row stride, discards alpha and owns the resulting BGR buffer. Camera
and Video retain their existing error and end-of-file behavior.

### Local builds

SDK-disabled development remains the default (`DIVERGENCESPLITTER_ENABLE_NDI=OFF`).
To enable input, download the official SDK and extract it with innoextract, then:

```powershell
cmake --preset full-release -DDIVERGENCESPLITTER_ENABLE_NDI=ON -DNDI_SDK_DIR=C:/private/ndi-sdk/app
cmake --build --preset full-release --parallel
ctest --preset full-release --output-on-failure
build/full-release/divergencesplitter-cli.exe --ndi-check
build/full-release/divergencesplitter-cli.exe --ndi-list
```

ON requires Windows x64, the main and dynamic-load headers, runtime DLL,
runtime notices and the reviewed SDK agreement. Configure fails when any is
missing or its reviewed binary/license hash differs. The SDK import library is
not linked. Development SDKs / installers must not be committed to this repo.
The runtime is copied next to build executables; the loader uses that absolute
application-local path and does not fall back to the working directory or PATH.

### CI acquisition and release contents

Set repository Secret `NDI_SDK_URL_WINDOWS` to the official Windows SDK URL.
The acquisition and package verification scripts are Python:
`tools/get_ndi_sdk.py` and `tools/verify_windows_zip.py`.
`tools/ndi-sdk-lock.json` pins the exact 6.3.2.0 installer SHA-256, runtime and
license hashes, and innoextract 1.9 checksum. The installer version, Authenticode
publisher, extracted headers, runtime version and hashes are verified before
Configure. Missing Secrets and mismatched downloads fail the required ON build;
there is no silent fallback. SDK contents are never put in public Actions caches.
Fork pull requests run OFF only and receive no Secret. Same-repository PRs and
`main` push / manual runs require both ON and OFF builds and tests. Push
triggers do not list temporary work branches.

Only the ON job uploads the official Windows ZIP. It contains
`Processing.NDI.Lib.x64.dll`, `Processing.NDI.Lib.Licenses.txt`, and the application
use terms in `licenses/NDI-TERMS.txt`. These DLL and third-party notices are the
only SDK-derived files redistributed. The SDK agreement PDF is checked at build
time for existence and SHA-256 only; it is excluded from the ZIP. Read the
[official NDI SDK License Agreement](https://ndi.link/ndisdk_license). No SDK headers,
import libraries, SDK installers, test sender or NDI Tools are packaged. CI
checks these files and their hashes, CLI and GUI startup, and application-local
runtime initialization from the extracted ZIP with runtime environment variables
removed and PATH restricted to that ZIP / Windows system directories.

DivergenceSplitter remains MIT. The NDI runtime is proprietary and subject to
its separate [use terms](licenses/NDI-TERMS.txt),
[official SDK agreement](https://ndi.link/ndisdk_license) and third-party
notices. See [the redistribution notice](licenses/NDI.md), the [official licensing
requirements](https://docs.ndi.video/all/developing-with-ndi/sdk/licensing) and
[permitted distribution files](https://docs.ndi.video/all/developing-with-ndi/sdk/software-distribution).
The exact extracted SDK agreement was compared byte-for-byte with the official
agreement during integration. Updates require review of that agreement, its
section 3(d) application terms, notices, trademark/link requirements, permitted
platforms and latest-SDK requirement before publishing another runtime ZIP.

### Reception and stability verification

Fake-API CTest cases cover initialization, resource lifetimes, discovery changes,
name selection, timeout / resume, buffer ownership, stride, six pixel formats,
exceptions and prompt pipeline shutdown. Qt tests cover asynchronous discovery,
offline draft names, selection and profile / transform restoration.

With the real SDK enabled, `ndi_sdk_initialization` tests startup/shutdown and
`ndi_sdk_loopback` creates an actual SDK sender on Windows. It verifies discovery,
reception, BGR conversion, Crop/Resize, preview buffer, Scenario start detection,
sender destruction/recreation, automatic reconnection and shutdown. This is a
real local network reception test, separate from initialization and fake tests.
For a longer local run (seconds, up to 3600):

```powershell
$env:NDI_SOAK_SECONDS = '600'
build/full-release/divergencesplitter_ndi_loopback_tests.exe
```

Also validate an independent sender (for example NDI Test Patterns from
[NDI Tools](https://ndi.video/tools/)) over the target network: discovery, source
selection, live preview, Scenario detection, stop/restart recovery, saved profile
reload and a sustained run. Record sender/receiver versions, duration, frame
counts, errors and network topology. A local loopback or initialization test
alone does not certify interoperability or long-term stability on another network.
