# Testing

[Developer guide](README.md) · [Build prerequisites](building.md)

## CTest

From `cpp/` after configuring the matching preset:

```powershell
cmake --build --preset full --parallel
ctest --preset full --output-on-failure
ctest --preset full -N
ctest --preset full -R 'Conditions|ScenarioLoader|ScenarioRuntime' --output-on-failure
```

Use `core`, `core-release`, or `full-release` consistently with the build you want
to test. Core presets omit Qt tests; NDI defaults OFF. CMake registers individual
GoogleTest cases and a Qt test executable. Qt runs with an offscreen platform and
the configured plugin/DLL paths; `ctest` sets these automatically.

| Area | Main tests and intent |
| --- | --- |
| Detector | [`detector_tests.cpp`](../../tests/detector_tests.cpp): formulas, alpha masks, size/channel constraints, hashes, histogram and correlation cases. |
| Condition | [`condition_tests.cpp`](../../tests/condition_tests.cpp): short-circuit order, edge history, elapsed start, continuous Hold, Once/Nth and Then progression/reset. |
| YAML | [`scenario_loader_tests.cpp`](../../tests/scenario_loader_tests.cpp): schema failures, nested conditions, paths, ROI, reference transformations. |
| Profile | [`profile_tests.cpp`](../../tests/profile_tests.cpp): JSON fields, source types, settings and serialization. |
| Capture | [`camera_tests.cpp`](../../tests/camera_tests.cpp), [`normalizer_tests.cpp`](../../tests/normalizer_tests.cpp), [`ndi_tests.cpp`](../../tests/ndi_tests.cpp): device resolution, transforms, fake NDI lifetimes/formats/timeouts/recovery. |
| Cache/runtime | [`frame_cache_tests.cpp`](../../tests/frame_cache_tests.cpp), [`scenario_runtime_tests.cpp`](../../tests/scenario_runtime_tests.cpp), [`instance_runtime_tests.cpp`](../../tests/instance_runtime_tests.cpp): shared evaluation, phase routing, resets, pending controls, fake-Bridge dispatch, event/reconnect/unknown-outcome handling. |
| UI/logging | [`ui_tests.cpp`](../../tests/ui_tests.cpp), [`logging_tests.cpp`](../../tests/logging_tests.cpp): draft transforms, reference validation, discovery responsiveness, Reset All hold/cancel, widgets, log rotation. |

Fake tests are deterministic checks of application behavior. They do not establish
that a physical camera, external sender, or user's LiveSplit installation works.

## Real LiveSplit.Bridge TestHost integration

Enable the optional executable:

```powershell
cmake --preset full -DDIVERGENCESPLITTER_BUILD_TESTHOST_TESTS=ON
cmake --build --preset full --parallel
```

Build the same Bridge TestHost revision used in
[`cpp23.yml`](../../../.github/workflows/cpp23.yml). In a separate directory, using
Git and .NET SDK 10 (the Bridge repository also has its own build prerequisites):

```powershell
git clone --recurse-submodules https://github.com/Nanahuse/LiveSplit.Bridge.git C:/src/LiveSplit.Bridge-TestHost
git -C C:/src/LiveSplit.Bridge-TestHost checkout 4c14c0161eacd50b05411c0d20f5eff523e9c155
git -C C:/src/LiveSplit.Bridge-TestHost submodule update --init --recursive
dotnet build C:/src/LiveSplit.Bridge-TestHost/tests/LiveSplit.Bridge.TestHost/LiveSplit.Bridge.TestHost.csproj --configuration Release
```

Back in `cpp/`, use the existing runner with an unused local port:

```powershell
python tools/run_testhost.py --testhost C:/src/LiveSplit.Bridge-TestHost/tests/LiveSplit.Bridge.TestHost/bin --test-exe build/full/divergencesplitter_testhost_tests.exe --port 54157
```

The helper starts the TestHost, keeps stdin open, waits for READY, sets
`DIVERGENCESPLITTER_TESTHOST_PORT` and
`DIVERGENCESPLITTER_TESTHOST_ALLOW_CONTROL=1`, runs the tests, and stops the host.
The current tests exercise Query/events and Pause/Resume controls, starting and
resetting the TestHost timer as needed. Use an isolated TestHost, not a live run.

For a host you started yourself, set `DIVERGENCESPLITTER_TESTHOST_PORT` before
CTest. Without it, these tests **skip**; a green CTest summary alone does not mean
real Bridge controls were tested. Controls also skip unless
`DIVERGENCESPLITTER_TESTHOST_ALLOW_CONTROL=1` is set. A directory passed to
`--testhost` must contain exactly one TestHost executable.

## Real NDI tests

With NDI enabled and its pinned SDK available:

```powershell
ctest --preset full-release -R '^ndi_sdk_' --output-on-failure
$env:NDI_SOAK_SECONDS = '600'
.\build\full-release\divergencesplitter_ndi_loopback_tests.exe
Remove-Item Env:NDI_SOAK_SECONDS
```

`ndi_sdk_initialization` checks startup/shutdown. `ndi_sdk_loopback` creates a real
local SDK sender and verifies discovery, selection, received BGR conversion,
Crop/Resize, preview, scenario Start detection, sender destruction/recreation,
reconnection, and shutdown. The soak duration can be extended up to 3600 seconds.
For a long direct run, invoke the executable as above; CTest's loopback timeout is
90 seconds.

Also verify an independent sender over the target network, for example a sender
from [NDI Tools](https://ndi.video/tools/). Check selection, preview, detection,
stop/restart recovery, saved-profile reload, and sustained reception. Record
sender/receiver versions, duration, frame counts, errors, and topology. Local
loopback success alone does not verify another network or sender.

## Distribution helpers

```powershell
python -m unittest discover -s tools/tests -v
```

These tests check SDK acquisition and ZIP-verification helpers. Test the actual
packaged ZIP separately using the [distribution procedure](distribution.md).

## Validating documentation examples

Customize the absolute video/scenario paths in
[`profile.example.json`](../../examples/profile.example.json), then run the built
CLI's `--profile <path> --check`. This uses the actual C++ Profile and scenario
loaders, including reference resizing, without sending timer controls.

For every complete scenario in [examples](../scenarios/examples.md), save its YAML
beside any referenced image, point the profile to it, and repeat the check. For
reference snippets that contain only a condition or detector mapping, embed them
in a complete scenario before loading. A JSON/YAML parser alone is not a schema
check. `--check` does not open the video, validate its codec, or compare detectors
against actual frame dimensions; inspect Monitor or use frame-based tests for
those aspects.

Review source paths and Markdown anchors, and check that only documentation and
example files changed with `git diff --check` and `git diff --name-only`.
