# Architecture

[日本語（正本）](architecture.md) | [English](architecture.en.md)

[Developer guide](README.en.md)

## Component boundaries

```text
Camera / Video / NDI
        |
  CapturePipeline thread
        |
  FrameNormalizer (Crop -> Resize)
        |
  shared newest frame + per-frame cache ----> Monitor preview
        |
        +----> InstanceRuntime 0 ----> ScenarioRuntime ----> Bridge client 0
        +----> InstanceRuntime 1 ----> ScenarioRuntime ----> Bridge client 1
                    |                     |
                    +------ diagnostics --+----> Qt GUI
```

| Component | Responsibility / source |
| --- | --- |
| Capture | [`src/capture/`](../../src/capture): device/mode enumeration, frame-source ownership, paced video reading, NDI conversion/discovery, capture thread. |
| Normalizer | [`frame_normalizer.cpp`](../../src/core/frame_normalizer.cpp): validates Crop/Resize and produces the normalized frame used by every instance. |
| Scenario/core | [`src/core/`](../../src/core): YAML loading, references, detector scores, condition trees, plain rules, RuleSequence. No GUI or network RPCs. |
| ScenarioRuntime | [`scenario_runtime.cpp`](../../src/runtime/scenario_runtime.cpp): selects rule groups from authoritative timer state, applies reset policies, tracks pending actions and diagnostic trees. |
| InstanceRuntime | [`instance_runtime.cpp`](../../src/runtime/instance_runtime.cpp): one worker per scenario/Bridge connection, frame delivery, events, reaction delay, control dispatch, reconnect, diagnostics. |
| Session/configuration | [`session.cpp`](../../src/runtime/session.cpp), [`configuration.cpp`](../../src/runtime/configuration.cpp): JSON loading, source creation, optional reference resize, session replacement and shutdown. |
| Bridge | [`livesplit_client.cpp`](../../src/runtime/livesplit_client.cpp), [`livesplit_adapter.cpp`](../../src/runtime/livesplit_adapter.cpp): client-library translation, query/event synchronization, local state/run revisions. |
| GUI | [`src/ui/`](../../src/ui): Qt Widgets pages and AppController; draft editing and snapshots, without doing timer control RPCs on the UI thread. |
| CLI | [`src/cli/main.cpp`](../../src/cli/main.cpp): profile/scenario validation, timed headless sessions, NDI initialization/discovery checks. |

## Frames and ownership

Capture publishes `shared_ptr<SharedFrameEvaluation>` with an owned normalized
frame, capture timestamp, sampled monotonic evaluation time, and shared per-frame
cache. An instance retains only the newest pending frame: stale frames are
replaced, not accumulated in an unbounded queue. Slow evaluation can miss transient
visual states. Capture FPS and evaluation count therefore need not be equal.

The per-frame cache shares equivalent detector results and grayscale/hash
preprocessing across instances. Keys include detector type, ROI, options, and
reference contents. Condition state is independent of that cache: each scenario
load constructs its own clocks, edge history, counters, and sequence position.
Preview owns a copy so UI rendering does not depend on a source's temporary
capture buffer.

NDI requests deinterlaced BGRX/BGRA. Conversion also handles UYVY/UYVA and RGBA/RGBX,
respects row stride, discards alpha, and owns the final BGR buffer. Reads wait at
most 50ms; ordinary timeouts keep the receiver alive. The SDK is dynamically loaded
from the executable directory, with no working-directory/PATH fallback and no
NDI import-library linkage. SDK-disabled builds use the same public capture API.

## Bridge and controls

The pinned `livesplit-bridge-client-cpp` library manages Protocol v4 transport and
its worker. The application wraps it with `LiveSplitBridgeClient` and maps its
snapshots/errors into application models. Control calls use the library's async
APIs and wait on the instance thread. GUI and capture threads never wait for those
RPCs. Reaction delay is measured from the captured frame timestamp.

`LiveSplitBridgeAdapter` attaches with a query, tracks session/state/run revisions,
and applies complete timer/reset events without querying the entire run each time.
Missing event state, session changes, run changes, or increased dropped-event
counts trigger synchronization. ScenarioRuntime rejects stale revisions and
requires resynchronization before accepting a different session baseline.

After successful control the instance queries authoritative state and feeds a
transition update back to ScenarioRuntime. A rejected/not-dispatched action can
reset its group for another evaluation. A `control_result_unknown` is never
blindly resent: the instance discards its scenario runtime, reconnects/resyncs,
and guards the same automatic operation against an unchanged authoritative
snapshot. This avoids duplicate controls when a response was lost.

ScenarioRuntime also has a one-second frame-evaluation timeout for pending actions;
this differs from transport response timeouts. Public rule selection/reset
semantics are centralized in the [YAML reference](../scenarios/yaml-reference.en.md).
Manual Reset is queued and processed on the instance thread using current state;
it is not a direct UI-thread RPC.

## Session and GUI lifecycle

Apply constructs new scenarios, sources, and instances before replacing the old
session. Starting capture opens input asynchronously, so success at Apply does
not guarantee later frame delivery. Session shutdown stops capture before
destroying the instance sinks, then stops instances and closes clients. Reference
resize happens during scenario loading, separately from input normalization.

AppController distinguishes the active Profile, a file path, and Settings;
ProfilePage owns the editable draft. Monitor refreshes on a 100ms timer;
Diagnostics refreshes every 300ms while visible. NDI discovery runs outside the
GUI thread and preserves offline draft names. Monitor displays the preview from
the active runtime.

See [testing](testing.en.md) for fake and real integration coverage and
[building](building.en.md) for target/dependency boundaries.
