# Scenario authoring

[Documentation home](../../README.md)

A scenario is a `.yaml` or `.yml` file describing a start condition, optional
reset/finish-recovery conditions, and rules for each LiveSplit segment. A Profile
connects that file to a local Bridge port and a video input.

1. Try the [minimal scenario](../../examples/minimal-scenario.yaml) using
   [Getting started](../getting-started.md).
2. Read the [YAML reference](yaml-reference.md) for structure, actions, evaluation
   order, paths, anchors, and runtime resets.
3. Choose a [detector](detectors.md), then wrap it in `detected` and any needed
   [conditions](conditions.md).
4. Adapt [examples](examples.md), Apply, and inspect scores in
   [Diagnostics](../user-guide.md#diagnostics).

Keep the coordinate system stable: input Crop/Resize runs before detector ROI.
Reference-image resizing is a separate Profile option; see
[configuration](../configuration.md#crop-resize-and-reference-images).

Scenarios are evaluated only when normalized frames arrive and the instance has
a valid Bridge state. Time conditions use monotonic application time, not
LiveSplit's real time or game time, and do not fire without another evaluation.

The public schema is implemented by
[`scenario_loader.cpp`](../../src/core/scenario_loader.cpp); condition and detector
behavior is covered by the [test suite](../development/testing.md).
