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
build/full/monitor_history_benchmark.exe render
```

The tool is not installed or included in the distribution ZIP. The first command
copies all histories; `selected` requests six paths representing visible graphs.
Both modes still retrieve all rule/condition metadata and build the card model.

The fixture preloads 60 seconds at 60 evaluations/second, visiting each split in
sequence. Each split has ten nodes. The shared Reset rule has ten nodes in the
representative cases and 1000 in the stress case; an unevaluated ten-node Start
rule is also present. Elapsed children under an All node advance even during
short evaluation, generating actual dense history through the collector.

Twenty polls target a 100 ms interval. A concurrent evaluator targets a 16 ms
interval. `snapshot` includes `ScenarioRuntime::diagnostics()` while holding its
mutex; `prepare` includes `card_model()` and `prepare_history()`. Evaluator timings
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

Copying all retained histories caused meaningful evaluator stalls, so the Monitor
now sends a per-Instance set of requested paths. Visible small plots, an open
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

## Compact graph renderer comparison

`render` compares 140 × 22 logical-pixel mini graphs using the same 3600-point
prepared score history, including gaps, resets and errors. It also measures the
complete table row with state icon and label. Every tested row is deliberately
visible, even at 100 rows. Five warmup frames precede thirty measured frames.
These timings include CPU geometry generation and ImGui/ImPlot submission, not
GPU rendering, history retrieval or plot preparation.

| Visible rows | Renderer | CPU P50 / P95 (ms) | Vertices per frame |
| ---: | --- | ---: | ---: |
| 20 | ImPlot | 0.637 / 0.736 | 142,418 |
| 20 | ImDrawList | 0.493 / 0.531 | 27,618 |
| 20 | Complete compact rows | 0.497 / 0.523 | 28,578 |
| 100 | ImPlot | 3.257 / 4.173 | 712,018 |
| 100 | ImDrawList | 2.414 / 2.538 | 138,018 |
| 100 | Complete compact rows | 2.491 / 2.873 | 142,818 |

The mini graph therefore uses ImDrawList with a per-pixel first/min/max/last
envelope within each continuous segment. At 100 rows this reduced median CPU
time by about 26% and vertices by about 81% versus ImPlot. Interactive detailed
graphs retain ImPlot. Actual window clipping normally shows fewer than 100 rows;
this synthetic comparison does not replace profiling a user's real scenario.
