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

InstanceRuntime retains an unsent action and its due time while processing events,
fresh frames, and manual Reset. Due time uses the capture timestamp plus Reaction
time. It rechecks pending/control state before dispatch and cancels if either has
changed. Unrelated events and unchanged queries leave the wait intact. Manual
Reset and automatic Reset interrupting a normal reaction wait bypass the delay
and cancel the unsent normal action.

RPC success calls `action_accepted` with monotonic time to start the separate
normal-action or Reset confirmation wait. Success does not require an immediate
query: Bridge events applied through the adapter can confirm the state change.
Wait selection and confirmation rules are in the
[YAML reference](../scenarios/yaml-reference.en.md#pending-actions-and-confirmation).
Independently of frame delivery, InstanceRuntime checks the one-second deadline,
queries on expiry, then calls `state_wait_timed_out` to release unconfirmed pending
state and reset its rule group. A query failure enters reconnect/resynchronization
through exception handling before another frame is evaluated.

A rejected or unsent normal action uses `action_not_dispatched` to reset its
group. Reset has separate pending state; cancelling it before dispatch preserves
a sent normal action's wait. A rejected Reset RPC triggers a query followed by
`settle_rejected_reset`, which clears both old waits and resets the Reset group
and the group for the current phase/index. A later frame makes a fresh decision.
Manual Reset is queued to the instance thread, without a direct UI-thread RPC.

A `control_result_unknown` is never blindly resent: the instance discards its
scenario runtime, reconnects/resyncs, and guards the same automatic operation
against an unchanged authoritative snapshot. This avoids duplicate controls when
a response was lost.

## Session and GUI lifecycle

Apply constructs new scenarios, sources, and instances before replacing the old
session. Starting capture opens input asynchronously, so success at Apply does
not guarantee later frame delivery. Session shutdown stops capture, stops
instances and closes clients, then destroys the instance sinks. Reference
resize happens during scenario loading, separately from input normalization.

AppController distinguishes the active Profile, a file path, and Settings;
ProfilePage owns the editable draft. Monitor refreshes on a 100ms timer;
Diagnostics refreshes every 300ms while visible. NDI discovery runs outside the
GUI thread and preserves offline draft names. Monitor displays the preview from
the active runtime.

[`ProfilePreview`](../../src/ui/profile_preview.cpp) owns input on a worker
independent of the Session, performing capture, normalization, and QImage
conversion there. The GUI presents the latest image at about 10 Hz. Comparing
input identity without transform settings lets Crop/Resize edits avoid reopening
the source. A retained frame allows transform updates while input is paused.
Changing input closes the previous source before opening the next. Hiding the
page, disabling preview, or starting a Session releases it. Stopping preview
before Session startup prevents duplicate use of the input.

Monitor computes processing FPS from instance generation and evaluation counts,
and builds current-condition, threshold, and score summaries from diagnostic
snapshots. Diagnostics retains the full tree and maximum scores.

See [testing](testing.en.md) for fake and real integration coverage and
[building](building.en.md) for target/dependency boundaries.
