# Technical MVP Review

## Baseline

- Repository: `https://github.com/Nanahuse/DivergenceSplitter`
- Branch: `feature/technical-mvp-review`
- HEAD: `d5322b487104433c2d6b633540232ecd36882363`
- Python: `3.14.6`
- uv: `0.11.32`
- OS: `Microsoft Windows 11 Pro` (`Windows-11-10.0.26200-SP0`)
- Review date: `2026-09-09`

The reviewed HEAD is the latest `origin/main` and contains the merged UI
reconstruction change.

## MVP-G1 Result

`CAMERA_VALIDATION.md` is not present in the repository. No repository
evidence was found for the required real-camera checklist:

- real Windows camera device enumeration and capture-mode enumeration
- configuration round-trip using a real camera
- camera open, effective resolution, effective FPS, and continuous capture
- Start/Stop, disconnect/reconnect, and Stop while disconnected
- packaged executable camera verification

The README requests that these checks be performed manually, but it does not
record a completed result. Therefore MVP-G1 cannot be treated as `PASS`.

## Evaluation

### A. Configuration

Result: `PASS`

Strict version/source/instances/runtime models, camera mode fields, validation,
JSON loading/saving, and round-trip tests are present. The README examples use
the current version-1 schema.

### B. Frame Source

Result: `PARTIAL`

Video and OpenCV camera sources implement prepare/read/close, context-manager
cleanup, and error actions. Runtime camera construction resolves an exact
enumerated mode and calls `windows_capture_device_list.open_video_capture`.
Real hardware behavior is not verified because MVP-G1 evidence is missing.

### C. Frame Pipeline

Result: `PASS`

Capture, `LatestFrameBuffer`, normalization, shared `FrameContext`, and bounded
latest-frame processing are implemented and covered by runtime tests. The
benchmark reports overwritten frames rather than unbounded queue growth.

### D. Detector / Condition

Result: `PASS`

The public detector and condition implementations are covered by unit tests and
are available to Python scenarios. The review did not add or change detector
behavior.

### E. Scenario

Result: `PASS`

Python scenario loading/validation and YAML's explicitly supported subset are
implemented and tested. Scenarios contain no LiveSplit connection. Unsupported
YAML types are rejected explicitly.

### F. Multi-instance Runtime

Result: `PASS`

Configuration, runtime construction, shared frame processing, per-instance
scenario evaluation, per-instance Bridge workers, and Settings editing are
implemented and tested.

### G. LiveSplit Bridge

Result: `PASS`

The worker uses one connection per instance, receives fresh snapshots, queues
reset with priority, reconnects/resynchronizes, and does not blindly retry an
action after an unknown result. Unit tests cover the adapter and worker. A
real external LiveSplit Bridge session was not available during this review.

### H. Runtime Lifecycle

Result: `PASS`

Session state transitions, double-start rejection, cooperative stop, worker
join, source cleanup, error propagation, and terminal results are implemented
and covered by tests.

### I. Diagnostics / Metrics

Result: `PASS`

`OperationalDiagnostics` exposes non-consuming metrics and observations to the
UI. Runtime FPS, processing FPS, detector observations, and error reporting
are covered by runtime/UI tests.

### J. UI

Result: `PARTIAL`

The main UI, page navigation, Monitor preview/diagnostics, Configuration page,
native Windows file picker adapter, About, Licenses, and modal Error dialog
are implemented. The packaged executable remained alive for a five-second
smoke test. Native picker selection, real camera enumeration, and full
Start/Stop behavior were not manually validated with a real device.

### K. Error Handling

Result: `PASS`

Failure categories are represented by `SessionFailureKind`, not inferred by
parsing exception messages. Error presentation deduplicates the same terminal
result and is covered by tests.

### L. Packaging

Result: `PARTIAL`

The latest `main` UI distribution workflow succeeded, and a local one-file
PyInstaller build succeeded with Dear PyGui, OpenCV, and
`windows_capture_device_list` collection. The resulting executable was
started successfully for a five-second smoke test. Camera enumeration and
camera operation inside the packaged executable remain unverified.

### M. CI / Test

Result: `PASS`

Local verification succeeded:

- `uv run ruff format --check .`: passed
- `uv run ruff check .`: passed
- `uv run ty check --error-on-warning .`: passed
- `uv run pytest -q`: `534 passed, 56 subtests passed`
- `uv run pytest packages/divergencesplitter/tests -q`: `200 passed, 15 subtests passed`
- `uv run pytest packages/divergencesplitter-runtime/tests -q`: `178 passed, 41 subtests passed`
- `uv run pytest packages/divergencesplitter-ui/tests -q`: `130 passed`
- `uv run python tools/generate_ui_license_inventory.py --check`: passed

The latest `origin/main` CI, Core distribution, and UI distribution workflows
also completed successfully at this HEAD.

### N. Performance

Result: `PARTIAL`

The bounded-memory baseline exists for 640x360 and 1280x720. The review
benchmark was reproducible over both 5 and 15 seconds, but it was below the
documented initial SLO and below the recorded baseline:

| Resolution | Current 15s processing FPS | Recorded baseline | Initial SLO |
| --- | ---: | ---: | ---: |
| 640x360 | 46.42 | 55.05 | 50 |
| 1280x720 | 13.20 | 15.00 | 14 |

Current 15s peak traced memory was 4.419 MiB and 17.217 MiB respectively, so
the bounded-memory property remained stable. No optimization was started in
this gate.

### O. Documentation

Result: `PARTIAL`

README schema, supported YAML subset, Bridge constraints, and performance
documentation match the implementation. `CAMERA_VALIDATION.md` and
`IMPLEMENTATION_PLAN.md` are absent, and no completed real-camera validation
record or standalone example files were found.

## Repository-wide Dead Path Review

- `CAP_ANY` remains as a low-level `OpenCvCameraSource` default and test seam;
  runtime configuration does not use it and instead opens an enumerated mode
  through `windows_capture_device_list`.
- No obsolete `device.id`, legacy camera width/height/FPS configuration, or
  scenario-owned connection schema was found.
- `instances[0]` occurrences are test assertions and do not represent a
  single-instance runtime path.

## Findings

### P0

None found in the code and automated verification.

### P1

- Required MVP-G1 real-camera validation evidence is missing. This blocks the
  explicit MVP-G2 PASS condition.
- The reproducible processing benchmark is below both the recorded baseline
  and initial SLO at 640x360 and 1280x720. The detector bottleneck should be
  investigated in a separate performance task.
- Packaged executable camera enumeration, camera capture, disconnect/reconnect,
  and packaged Start/Stop behavior are not verified.

### P2

- Add and maintain `CAMERA_VALIDATION.md` and `IMPLEMENTATION_PLAN.md`.
- Add standalone configuration/scenario example files if they are intended as
  release artifacts.
- Perform an external LiveSplit Bridge end-to-end run and record its results.

## Required Next Work

1. Run the MVP-G1 checklist on a real Windows camera and record the result in
   `CAMERA_VALIDATION.md`.
2. Repeat the checklist with the packaged executable, including camera
   enumeration, selected mode capture, Start/Stop, disconnect/reconnect, and
   Stop while disconnected.
3. Investigate the reproducible detector performance regression without
   changing the MVP architecture.
4. Re-run the full gate after the evidence and performance disposition are
   complete.

## Final Decision

MVP-G2: NOT READY

The decision is required by the missing MVP-G1 evidence and unverified
real-camera/package behavior. Automated tests, static checks, CI, packaging
build, and bounded-memory benchmark behavior alone are insufficient to mark
this Technical MVP as `PASS`.
