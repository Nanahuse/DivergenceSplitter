# Performance baseline

Run the checked-in measurement with:

```console
uv run python benchmarks/measure_processing.py --duration 5
```

The workload supplies a preallocated BGR frame at a 60 fps cadence through the
real single-slot `LatestFrameBuffer`. A processing thread evaluates
`MeanBrightnessDetector`, `ColorRangeDetector`,
`DifferenceHashSimilarityDetector`, and `TemplateMatchDetector` once per frame,
then reads one cached result. It reports capture-to-completion and detector p95
latency, cache-hit p95 latency, overwritten frames, and peak Python-traced
memory. It does not emulate camera-driver copies, scenario-specific reference
images, or network latency.

## 2026-09-03 baseline

Environment and results are recorded from the Windows development host in the
one-line output below. Rerun the command on release hardware before treating
the values as capacity guarantees.

```text
benchmark.environment python=3.14.6 platform=Windows-11-10.0.26200-SP0 duration_seconds=5.0 target_input_fps=60.0 scenario=four_builtin_detectors bridge=not_measured
benchmark.processing resolution=640x360 input_fps=59.84 processing_fps=55.05 published=300 processed=276 overwritten=24 capture_to_completed_p95_ms=33.208 detectors_p95_ms=18.995 cache_hit_p95_ms=0.008 peak_traced_mib=4.309 detector.MeanBrightnessDetector.p95_ms=0.506 detector.ColorRangeDetector.p95_ms=0.512 detector.DifferenceHashSimilarityDetector.p95_ms=4.299 detector.TemplateMatchDetector.p95_ms=14.628
benchmark.processing resolution=1280x720 input_fps=59.22 processing_fps=15.00 published=300 processed=76 overwritten=224 capture_to_completed_p95_ms=82.298 detectors_p95_ms=69.044 cache_hit_p95_ms=0.006 peak_traced_mib=17.185 detector.MeanBrightnessDetector.p95_ms=1.570 detector.ColorRangeDetector.p95_ms=2.066 detector.DifferenceHashSimilarityDetector.p95_ms=10.537 detector.TemplateMatchDetector.p95_ms=55.997
```

The 720p workload does not process every input frame. The buffer remains
bounded and drops stale frames, but the aggregate detector cost is the current
bottleneck. Per-detector fields from subsequent runs identify which detector
dominates before any parallelism is considered.

A 15-second confirmation processed 831/900 frames at 640x360 with 4.453 MiB
peak traced memory, and 224/900 frames at 1280x720 with 17.224 MiB. Compared
with the five-second peaks (4.309 MiB and 17.185 MiB), both remained within
0.15 MiB despite the additional 600 input frames. Template matching remained
the dominant detector at 14.501 ms and 57.813 ms p95 respectively.

## Initial SLO

For the recorded four-detector workload:

- measured input throughput must remain at least 58 fps;
- processing throughput must remain at least 50 fps at 640x360 and 14 fps at
  1280x720;
- capture-to-completion p95 must remain below 50 ms at 640x360 and 100 ms at
  1280x720;
- the single-slot buffer must not accumulate frames, and peak traced memory
  must remain stable when the duration is increased;
- cached detector lookup p95 must remain below 0.10 ms.

Processing every 60 fps frame is a performance target, not an initial SLO. It
is currently unmet at both resolutions (55.05 fps and 15.00 fps). The runtime's
intended degradation is visible frame replacement rather than queue growth;
optimize the measured detector bottleneck before considering parallelism.

Bridge latency is intentionally not assigned a local SLO: an in-process test
double does not represent ZeroMQ, LiveSplit's UI thread, or host load. Runtime
logs identify Bridge timeouts and action outcomes; an end-to-end Bridge latency
baseline must be recorded on the deployment host before release.
