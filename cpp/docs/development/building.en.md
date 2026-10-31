# Building

[日本語（正本）](building.md) | [English](building.en.md)

[Developer guide](README.en.md) · [Testing](testing.en.md) · [Distribution](distribution.en.md)

## Prerequisites

For Windows x64 builds, install:

- Visual Studio 2022 or 2026 with the Desktop development with C++ workload and
  Windows SDK; use an x64 Developer PowerShell with a C++23-capable MSVC toolset.
- CMake 3.25 or later and Ninja, both on PATH.
- A bootstrapped [vcpkg](https://github.com/microsoft/vcpkg) checkout; set
  `VCPKG_ROOT` to its absolute directory.
- Python 3.10 or later for build/distribution helpers. CMake requires the
  interpreter even when only building core. Select it with
  `-DPython3_EXECUTABLE=C:/tools/python/python.exe` if needed.
- Git and network access for initial dependency and Bridge downloads.

The manifest [`vcpkg.json`](../../vcpkg.json) pins a builtin baseline and supplies
OpenCV 4 (Core, Imgproc, Imgcodecs, Videoio and selected codec/camera features),
yaml-cpp, nlohmann/json, and Boost.Asio/Beast. Its `tests` feature adds GoogleTest;
`ui` adds Qt 6 qtbase. No opencv_contrib dependency is needed for hash detectors.

## Configure, build, run

From the repository root in Developer PowerShell:

```powershell
$env:VCPKG_ROOT = 'C:/vcpkg'
cd cpp
cmake --preset full
cmake --build --preset full --parallel
ctest --preset full --output-on-failure
.\build\full\DivergenceSplitter.exe
```

The first configure can take substantial time to build dependencies, especially
Qt. Keep the DLLs and deployed Qt plugins alongside the build executable. CMake
copies debug Qt plugins for Debug; Release uses `windeployqt` when available.
The CLI is `build/full/divergencesplitter-cli.exe`; see
[CLI usage](../troubleshooting.en.md#command-line-checks).

For core/runtime work without Qt:

```powershell
cmake --preset core
cmake --build --preset core --parallel
ctest --preset core --output-on-failure
```

## Presets and options

All presets use Ninja, the `VCPKG_ROOT` toolchain, and separate
`cpp/build/<preset>` directories. Run preset commands from `cpp/`.

| Preset | Configuration | UI | vcpkg features |
| --- | --- | --- | --- |
| `core` | Debug | Off | `tests` |
| `core-release` | Release | Off | `tests` |
| `full` | Debug | On | `tests;ui` |
| `full-release` | Release | On | `tests;ui` |
| `ci` | Release | On, externally supplied Qt | `tests`; TestHost tests enabled |

`ci` expects Qt discoverable through `CMAKE_PREFIX_PATH` or `Qt6_DIR`. The workflow
installs Qt 6.8.3 MSVC 2022 x64 externally to avoid building Qt in vcpkg. For a local
equivalent, set `-DCMAKE_PREFIX_PATH=C:/Qt/6.8.3/msvc2022_64` at configure time and
use the matching toolchain architecture. Both Qt Widgets and Qt Test are required
when the UI option is on.

| CMake option | Default | Meaning |
| --- | --- | --- |
| `DIVERGENCESPLITTER_BUILD_UI` | `ON` | Build Qt UI and GUI executable. |
| `DIVERGENCESPLITTER_BUILD_TESTS` | `ON` | Build/register tests; GoogleTest required. |
| `DIVERGENCESPLITTER_BUILD_TESTHOST_TESTS` | `OFF` | Add the optional real Bridge integration executable when tests are enabled. |
| `DIVERGENCESPLITTER_FETCH_BRIDGE` | `ON` | Fetch/build the required Bridge client target. OFF requires the parent build to provide `livesplit_bridge::livesplit_bridge`. |
| `DIVERGENCESPLITTER_BRIDGE_TAG` | `v0.1.0` | Tag/commit used by FetchContent. |
| `DIVERGENCESPLITTER_ENABLE_NDI` | `OFF` | Enable official SDK receiver on Windows x64. |
| `NDI_SDK_DIR` | Empty | Extracted SDK root used with NDI enabled. |

To use an existing client checkout without downloading another copy, configure
with `-DFETCHCONTENT_SOURCE_DIR_LIVESPLIT_BRIDGE=C:/src/livesplit-bridge-client-cpp`.
Keep it at the intended pinned version when verifying reproducibility. Application
targets are `divergencesplitter_core`, `divergencesplitter_runtime`,
`divergencesplitter_cli`, and (with UI) `divergencesplitter_ui` / `DivergenceSplitter`.

## NDI-enabled builds

NDI defaults to OFF so ordinary development needs no SDK. To build ON, obtain the
official SDK matching [`ndi-sdk-lock.json`](../../tools/ndi-sdk-lock.json)
(currently 6.3.2.0), extract its Windows payload with innoextract, and point
`NDI_SDK_DIR` at the directory containing `Include`, `Bin/x64`, and
`NDI SDK License Agreement.pdf`. Do not commit SDK development files or installers.

```powershell
cmake --preset full-release -DDIVERGENCESPLITTER_ENABLE_NDI=ON -DNDI_SDK_DIR=C:/private/ndi-sdk/app
cmake --build --preset full-release --parallel
ctest --preset full-release --output-on-failure
.\build\full-release\divergencesplitter-cli.exe --ndi-check
.\build\full-release\divergencesplitter-cli.exe --ndi-list
```

Configuration requires Windows x64, `Processing.NDI.Lib.h`,
`Processing.NDI.DynamicLoad.h`, the runtime DLL, runtime notices, and the reviewed
agreement. Missing files or pinned runtime/notice/agreement hash mismatches fail
configuration. The runtime DLL is copied beside the build executables and loaded
there by absolute path. Runtime installation elsewhere does not replace it.
For controlled download/verification in CI, see [distribution](distribution.en.md#ci-workflow).

## Build failures

- Missing compiler/Windows SDK: reopen an x64 Developer PowerShell.
- Missing toolchain: check `VCPKG_ROOT` and bootstrap vcpkg before configuring.
- Missing Qt: use `full` to build it through vcpkg, or supply the external Qt path
  for `ci`. Avoid mixing debug/release plugins and DLLs.
- NDI hash mismatch: use the pinned SDK; changing the pin requires a deliberate
  SDK/notice review, not bypassing verification.

For dependency, compiler, or SDK changes, use a separate build directory or preset
to avoid stale cache settings. Packaging has additional notice requirements in
the [distribution guide](distribution.en.md).
