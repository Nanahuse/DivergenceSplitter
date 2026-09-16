# Benchmarks

This directory holds the reproducible measurements used to reason about
DivergenceSplitter's performance.

## Runtime benchmark

`measure_processing.py` drives the production runtime path (synthetic 60 fps
source, `LatestFrameBuffer`, `ProcessingRuntime`, per-instance threads) and
prints one machine-comparable line per case:

```console
uv run python benchmarks/measure_processing.py --suite quick
```

See the module docstring for the reported fields. It does not exercise the
desktop UI.

## UI performance instrumentation

The Flet UI now measures the work it owns on the hot path and flushes
aggregated results once per second. Timing is recorded with
`time.perf_counter_ns` and kept in memory; a hot path never formats a log
string per tick.

Measured sections:

| Section | What it covers |
| --- | --- |
| `monitor.snapshot` | `MonitorUpdateCoordinator.snapshot()`: controller state, diagnostics, observations, detector tree, instance status/run info, metrics |
| `monitor.apply` | `Monitor.apply(snapshot)` for the whole Monitor screen |
| `monitor.scenario_overview.presentation` | Pure `scenario_overview_view(...)` view-model construction |
| `monitor.diagnostics.presentation` | Pure `diagnostics_view(...)` view-model construction |
| `flet.page_update` | `page.update()` including Flet patch generation and the synchronous send |
| `preview.prepare` | `prepare_preview`: resize, channel conversion, contiguous copy |
| `preview.raw_image_render` | The awaited `RawImage.render(...)` call, including client acknowledgement |

### Output

Performance records use the same structured one-line format as the runtime
diagnostics, under the `divergencesplitter.ui.performance` logger:

```text
ui.performance section=monitor.snapshot count=10 avg_ms=0.18 max_ms=0.31
```

Records are emitted at `DEBUG` and only when the session log level is `DEBUG`
(the Configuration `Log level` dropdown). With `OFF`, recording is a single
`isEnabledFor` check per sample and no records are produced.

Desktop builds append the records to `performance.log`, next to
`diagnostics.log`. Source runs write both files to the current working
directory, or to the executable directory for frozen builds.

### Isolation switches

Three environment variables disable one section each without touching the
production configuration surface. They are read once at startup and are meant
for development and benchmarking only; unset, the UI behaves exactly as before.

| Variable | Effect |
| --- | --- |
| `DIVERGENCESPLITTER_PERF_DISABLE_PREVIEW=1` | `InputPreviewPanel.render_latest()` is not called. Runtime frame processing is untouched and the preview area remains. |
| `DIVERGENCESPLITTER_PERF_DISABLE_PAGE_UPDATE=1` | The Monitor loop still reads snapshots and updates control properties, but does not run `page.update()`. The display stops refreshing. |
| `DIVERGENCESPLITTER_PERF_DISABLE_DIAGNOSTICS=1` | The Diagnostics view model and control tree are neither built nor updated. The rest of the Monitor keeps working. |

Values `1`, `true`, `yes`, and `on` (case-insensitive) enable a switch.

## Comparison procedure

Run every case with the same configuration, the same input, and the same
duration. Enable `DEBUG` logging so both the runtime and UI records are
written. Record the runtime metrics shown in the Monitor's Global Status and
Scenario Overview.

| Case | Preview | Page update | Diagnostics |
| --- | --- | --- | --- |
| A: baseline | on | on | on |
| B: no preview | disabled | on | on |
| C: no page update | on | disabled | on |
| D: no diagnostics | on | on | disabled |
| E: About view | on (not drawn) | on | on |

Switch to the About page for Case E. The Monitor update loop keeps running, so
treat Case E as a screen-paint comparison rather than a full-loop comparison.

### Values to record

From the existing runtime metrics:

```text
input fps
processing fps
instance evaluation average latency
instance evaluation maximum latency
```

From the UI performance log:

```text
monitor.snapshot avg/max
monitor.apply avg/max
monitor.scenario_overview.presentation avg/max
monitor.diagnostics.presentation avg/max
flet.page_update avg/max
preview.prepare avg/max
preview.raw_image_render avg/max
```

### Interpreting the results

* **A → B improves processing FPS**: the input preview path dominates — the
  `RawImage` render, its client round-trip, or the preview image conversion.
* **A → C improves greatly**: `page.update()` dominates — control tree diffs,
  patch generation, or transport.
* **A → D improves**: the Diagnostics presentation and its control tree
  dominate.
* **A → E improves**: the cause is specific to drawing the Monitor screen. Note
  that the coordinator snapshot loop keeps running in all cases.
* **None improve much**: look next at the Flutter desktop process CPU load, CPU
  core contention with the runtime, Flet transport, or other Python/GIL load.

Do not commit a fix based on a single run; repeat each case and compare
consistent measurements.
