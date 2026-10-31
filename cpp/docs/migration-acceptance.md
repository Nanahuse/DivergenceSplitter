# C++ migration acceptance, stage 1

The Python packages remain available until checks against the user's actual
profiles, scenarios, sources, and LiveSplit installation are complete. Passing
the automated suite establishes the coverage below; it does not certify an
unavailable external device or a private scenario that was not supplied.

## Automated coverage

| Requirement | Evidence |
| --- | --- |
| Start/Split exactly once from dark → bright input | `RecordedPipeline.*` decodes generated MJPEG recordings through the production source, normalizer, YAML loader, instance worker, and fake Bridge operation history. `TestHost.RecordedVideoThroughYamlToRealBridgeControls` repeats Start/Split against the actual v4 Bridge component. |
| Split → external Undo → same-index reentry | `RecordedPipeline.ProfileYamlDecodeTransformStartSplitUndoAndReentry` checks the full recording's expected operation history. |
| Automatic Reset wins over Split without another reaction delay | `ScenarioRuntime.ResetHasPriorityOverSplit` and `InstanceRuntime.AutomaticResetIsEvaluatedDuringReactionWait` (Reset must arrive before a configured ten-second reaction delay). |
| Manual Reset during reaction time cancels the unsent Split | `InstanceRuntime.ManualResetCancelsUnsentSplitWithoutAnotherFrame`. |
| Independent normal/Reset confirmation and RPC-success deadlines | `ScenarioRuntime.ConfirmationTimeoutStartsAfterRpcSuccess`, rejected Reset, late Split, and Reset timeout cases; matching instance regressions. |
| Rejected Reset reconciles authoritative state | Instance tests cover unchanged and advanced split indices, automatic Reset to Not Running, fresh-frame reentry, and Query failure/reconnect. Scenario tests check current-phase sequence/Once progress and automatic Reset rearming. |
| Pause/Resume preserves pending Split and sequence progress | Scenario/instance regression cases plus actual TestHost pause/resume Events. |
| Bridge disconnection, recovery, and unknown results | Existing reconnect regression and normal/manual Reset unknown-result suppression tests. |
| Crop/Resize before detection | Recorded pipeline crops a permanently bright border, resizes the remaining image, and checks the expected dark/bright operation sequence; existing loader/detector tests retain Python OpenCV golden comparisons. |
| Multiple scenarios | `RecordedPipeline.MultipleYamlScenariosRemainIndependentOnSharedFrames` checks different histories for two YAML scenarios sharing decoded frames. |
| Profile JSON v2 / YAML | Recording E2E roundtrips a Profile before loading YAML; existing profile tests cover v1 migration and strict v2 save/load; loader tests cover supported conditions/detectors and `.py` rejection. |
| Draft preview before Apply | Qt tests check transform pixels, opened dimensions/FPS, worker-thread acquisition, GUI responsiveness, source replacement, paused input, error recovery, page visibility, and release before Session startup. |
| NDI SDK | SDK initialization and loopback discovery/receive/normalize/evaluate/reconnect; Qt test additionally stops a Session, receives its sender in the draft preview, then starts a Session again. |
| Monitor | Qt tests check the score/threshold summary and processing-FPS column. Reset All retains its existing hold/cancel tests. |

The recorded tests use frame barriers or sustained recording segments and compare
operation history/state rather than requiring identical thread timing. Reset
races and recovery properties already covered by runtime tests are reused rather
than duplicated in every recording.

MJPEG recordings use OpenCV's built-in AVI/MJPEG reader before trying platform
backends. On Windows, CAP_ANY otherwise tries Media Foundation (including GPU
codec discovery) first, which can delay open/Stop or fail to decode small test
recordings. Other formats still fall back to CAP_ANY. Decoder selection and
non-MJPEG fallback have separate source regressions; CI repeats these and the
recorded pipeline cases twenty times in each NDI configuration without extending
the five-second recording or two-second frame-barrier deadlines.

Recording failures report source open/read/close versus frame-sink progress,
decoder backend, captured/published frame counts, Bridge operation history and
queries, instance error, Scenario evaluation count, timer position, both pending
operations, rule errors, and CapturePipeline errors. The test joins capture before
checking its final error and stopping instance workers, so a barrier exception is
not hidden by an early fatal assertion or by teardown.

## Running the checks

From Developer PowerShell with the documented build dependencies:

```powershell
cd cpp
cmake --preset full -DDIVERGENCESPLITTER_BUILD_TESTHOST_TESTS=ON
cmake --build --preset full --parallel
ctest --preset full --output-on-failure
# Add the pinned official SDK to enable SDK and NDI Qt integration tests:
cmake --preset full -DDIVERGENCESPLITTER_ENABLE_NDI=ON -DNDI_SDK_DIR=C:/path/to/sdk
cmake --build --preset full --parallel
ctest --preset full --output-on-failure
python tools/run_testhost.py --testhost C:/path/to/TestHost/bin --test-exe build/full/divergencesplitter_testhost_tests.exe --port 54157
```

Without TestHost environment opt-in, its tests skip individual controls. Use the
helper for actual RPC verification; the ordinary CTest result alone does not
prove a live Bridge connection. Qt tests use an isolated settings directory.
Set `DIVERGENCESPLITTER_UI_CAPTURE_DIR` to save the draft preview's rendered UI.

## Checks against the user's environment

At local verification on 2026-10-30, the Profile camera list was empty, external
NDI discovery returned no senders, and the default application-data directory
contained no saved Profile/settings. No running production LiveSplit target or
user scenario was identified. The isolated TestHost and NDI loopback were
available and tested.

- [ ] Load each actual JSON Profile in C++; save to a **new** file and reload.
- [ ] Check every used YAML/reference image against representative frames,
      including score thresholds and transform boundaries.
- [ ] Rewrite any used Python `.py` scenario as YAML and compare its operation
      history on the same recording. C++ does not execute Python modules.
- [ ] Select each real Camera mode in Profile; confirm opened dimensions/FPS,
      crop/resize, hide/reopen, and Apply after preview.
- [ ] Discover and receive the actual external NDI sender; check paused sender,
      sender restart, draft edits, and transition to Session capture.
- [ ] Run Start/Split/Undo/Reset and disconnect/reconnect against the actual
      LiveSplit installation with Bridge v4 on a test run.

These checks remain the gate for deleting the old Python implementation in
stage 2. This change adds the C++ behavior and repeatable acceptance harness.
