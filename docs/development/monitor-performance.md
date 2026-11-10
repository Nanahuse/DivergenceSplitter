# Monitor snapshot and preparation benchmark

The repository's example scenarios have one split. No production profile was
provided for this review, so this benchmark uses representative synthetic 20- and
100-split scenarios, plus a deliberately large shared-condition stress case.
It measures history retrieval and preparation separately from detector cost and
GPU rendering. These measurements are not a guarantee for other machines.

## Reproduce

Configure a Windows Release UI build with
`-DDIVERGENCESPLITTER_BUILD_BENCHMARKS=ON`, then run:

```powershell
cmake --build build/full --target monitor_history_benchmark
build/full/monitor_history_benchmark.exe
build/full/monitor_history_benchmark.exe selected
build/full/monitor_history_benchmark.exe shared
build/full/monitor_history_benchmark.exe render
```

The tool is not installed or included in the distribution ZIP. The first command
copies all histories. `selected` requests six explicit paths. `shared` requests
recent 60-second series and the same six explicit paths. `render` draws a shared
chart with synthetic traces. All snapshot modes build the card model.

The fixture preloads 60 seconds at 60 evaluations/second, visiting each split in
sequence. Each split has ten nodes. The shared Reset rule has ten nodes in the
representative cases and 1000 in the stress case; an unevaluated ten-node Start
rule is also present. Elapsed children under an All node advance even during
short evaluation, generating actual dense history through the collector.

Twenty polls target a 100 ms interval. A concurrent evaluator targets a 16 ms
interval. `snapshot` includes `ScenarioRuntime::diagnostics()` while holding its
mutex. `prepare` includes `card_model()` and the plot preparation for the mode. Evaluator timings
include time waiting for that mutex. The all-history stress case overruns the
100 ms polling budget, so its actual polling rate is lower than 10 Hz.

## Windows/MSVC Release results

Measured with MSVC 19.51 on the development machine. Times are milliseconds;
P95 has only twenty snapshot/preparation observations and is close to the maximum.

| Splits / shared nodes | Retained samples | Mode | Snapshot P50 / P95 | Preparation P50 / P95 | Evaluation P95 / max |
| --- | ---: | --- | ---: | ---: | ---: |
| 20 / 10 | 72,800 | all | 19.19 / 31.45 | 0.96 / 1.98 | 8.69 / 23.81 |
| 20 / 10 | 72,800 | six paths | 3.40 / 4.47 | 0.14 / 0.27 | 1.03 / 3.98 |
| 100 / 10 | 76,000 | all | 21.31 / 24.22 | 0.98 / 1.56 | 11.12 / 22.05 |
| 100 / 10 | 76,000 | six paths | 3.46 / 3.94 | 0.18 / 0.26 | 0.28 / 3.88 |
| 100 / 1000 | 3,640,990 | all | 1424.93 / 1688.88 | 72.55 / 98.20 | 1339.49 / 1684.25 |
| 100 / 1000 | 3,640,990 | six paths | 3.91 / 5.18 | 0.20 / 0.32 | 1.21 / 5.24 |

Copying all retained histories caused meaningful evaluator stalls, so the earlier Monitor
sent a per-Instance set of requested paths. Visible mini graphs, an open
Condition inspector, and visible comparison plots contribute paths. Collapsed or
off-screen Conditions continue collecting history but do not copy sample buffers
or build plot arrays on each poll. Newly opened/scrolled plots load on the next
approximately 10 Hz update, at most about 100 ms later during normal UI operation.

The default diagnostics API still returns all histories when requested without a
path filter. Empty filters return the history identity with no sample series.
Filtering does not change collection, retention, generation boundaries or the
ability to reopen a past Condition. It is a retrieval optimization, not another
history manager. Expensive detector work and exceptionally many simultaneously
selected comparison series can still increase latency and need profiling with
the user's actual profile.

## Compact Monitor: contiguous snapshots

The compact view keeps the path filter. Snapshot sample storage now uses a
reserved vector, avoiding MSVC's many small deque allocations during copies.
The collector itself still uses the original bounded deque; collection and
retention are unchanged. Repeating `selected` with six paths gave these results:

| Splits / shared nodes | Retained samples | Snapshot P50 / P95 | Preparation P50 / P95 | Evaluation P95 / max |
| --- | ---: | ---: | ---: | ---: |
| 20 / 10 | 72,800 | 0.53 / 0.91 | 0.31 / 1.06 | 0.12 / 0.21 |
| 100 / 10 | 76,000 | 1.08 / 2.11 | 0.45 / 0.91 | 0.28 / 0.46 |
| 100 / 1000 | 3,640,990 | 1.50 / 3.47 | 0.25 / 0.49 | 1.21 / 2.06 |

## Earlier mini-graph renderer comparison

At `fe72082`, `render` compared 140 × 22 logical-pixel mini graphs using the same 3600-point
prepared score history, including gaps, resets and errors. It also measures the
complete two-column table row with a status-colored label and adjacent graph. Every tested row is deliberately
visible, even at 100 rows. Five warmup frames precede thirty measured frames.
These timings include CPU geometry generation and ImGui/ImPlot submission, not
GPU rendering, history retrieval or plot preparation.

| Visible rows | Renderer | CPU P50 / P95 (ms) | Vertices per frame |
| ---: | --- | ---: | ---: |
| 20 | ImPlot | 0.638 / 0.659 | 142,418 |
| 20 | ImDrawList | 0.498 / 0.864 | 27,618 |
| 20 | Complete compact rows | 0.496 / 0.522 | 28,258 |
| 100 | ImPlot | 3.271 / 3.537 | 712,018 |
| 100 | ImDrawList | 2.424 / 2.573 | 138,018 |
| 100 | Complete compact rows | 2.530 / 2.718 | 141,218 |

The mini graph therefore uses ImDrawList with a per-pixel first/min/max/last
envelope within each continuous segment. At 100 rows this reduced median CPU
time by about 26% and vertices by about 81% versus ImPlot. Interactive detailed
graphs retain ImPlot. Actual window clipping normally shows fewer than 100 rows;
this synthetic comparison does not replace profiling a user's real scenario.

The earlier layout used responsive Instance cards with a minimum
width of 360 logical pixels plus spacing. A 1186-pixel-wide native window showed
two simple Instance cards side by side, each 112 pixels high, below one toolbar
row. The main content occupied roughly 160 vertical pixels. At a 900-pixel window
width, the cards stacked into one column. A nested then → all → detected +
hold(detected) fixture used one progress/branch row and two condition rows per
card. Both fixtures used live synthetic video and independent TestHosts.


## Shared chart measurements at `66b8122`

The recent-window query selects only series with measurements, results or
errors in the window. It switches to an endpoint/extrema index above an
estimated 200,000 preview samples. Explicit Inspector paths retain their raw
samples. Measurements below use a Windows MSVC 19.51 Release build.

| Splits / Reset nodes | Retained samples | Snapshot P50 / P95 (ms) | Preparation P50 / P95 (ms) | Evaluation P95 / max (ms) |
| --- | ---: | ---: | ---: | ---: |
| 20 / 10 | 72,800 | 2.04 / 2.44 | 0.80 / 0.92 | 0.16 / 2.06 |
| 100 / 10 | 76,000 | 2.86 / 3.52 | 1.24 / 1.44 | 0.46 / 2.15 |
| 100 / 1000 | 3,640,990 | 9.20 / 11.19 | 2.08 / 3.07 | 2.59 / 11.10 |

With full recent buffers in the same stress case, snapshot and preparation P95
were 82.25 ms and 35.03 ms. The indexed query keeps the 60-second window and the
same series while reducing the number of copied points.

`render` feeds 3,600 raw score samples per synthetic series, including gaps and
events. This measures geometry preparation and draw-list CPU submission
separately. Production prepares geometry per snapshot and uses the indexed
query for dense histories.

| Series | Raw preparation P95 (ms) | Draw CPU P95 (ms) |
| ---: | ---: | ---: |
| 20 | 0.65 | 0.11 |
| 100 | 3.55 | 0.43 |
| 1000 | 28.58 | 3.08 |


## Stable shared chart measurements at `278a1a6`

The preview index and chart geometry use fixed 500 ms buckets on the monotonic
clock. Series count, snapshot time and Inspector selection no longer select a
different reduction policy. Prepared points retain timestamps, and each frame
translates them to the current display time. Draw submission collapses flat
edges and uses whole-pixel strokes for ImGui's baked antialiasing texture.

| Splits / Reset nodes | Snapshot P95 (ms) | Preparation P95 (ms) |
| ---: | ---: | ---: |
| 20 / 10 | 1.54 | 0.66 |
| 100 / 10 | 3.27 | 1.60 |
| 100 / 1000 | 14.52 | 9.60 |

In the synthetic waveform renderer test, draw CPU P95 was 0.07 ms for 20
series, 0.46 ms for 100 and 6.15 ms for 1,000. The 1,000-series case keeps more
points than the earlier series-count-dependent policy, which measured 3.08 ms.
Its snapshot and preparation can exceed one 60 FPS frame budget. These are CPU
measurements on the same Windows MSVC Release fixture.


## Shared trace mesh cache

The renderer submits each numeric trace on the first frame after a snapshot,
then stores the submitted vertices and indices. Scroll frames translate the
cached mesh into the current clip rectangle. The next snapshot reuses the
cache buffers. Resizing, DPI and theme changes regenerate the mesh for the new
display settings. The cache adds a vertex and index buffer per visible chart.

The `render` fixture runs at 60 draw frames per second of synthetic time and
refreshes the chart every six frames. CPU P95 values below exclude snapshot
retrieval and chart preparation.

| Synthetic series | Refresh draw P95 (ms) | Scroll draw P95 (ms) |
| ---: | ---: | ---: |
| 20 | 0.15 | 0.04 |
| 100 | 0.75 | 0.16 |
| 1000 | 6.99 | 1.53 |

At 1,000 series, the earlier renderer measured 6.15 ms P95 while tessellating
the trace every frame. Capturing the mesh adds work on refresh frames and
reduces the work on the five scroll frames between refreshes. Snapshot retrieval
and preparation can still exceed one 60 FPS frame budget in the stress case.
