# Developer guide

[Documentation home](../../README.md)

| Task | Guide |
| --- | --- |
| Understand component boundaries, threads, and control flow | [Architecture](architecture.md) |
| Configure CMake, dependencies, Qt, and the NDI SDK | [Building](building.md) |
| Run CTest, real Bridge integration, and NDI checks | [Testing](testing.md) |
| Produce and verify the Windows ZIP and notices | [Distribution](distribution.md) |

Public configuration belongs in the [Profile reference](../configuration.md) and
[scenario reference](../scenarios/yaml-reference.md). Keep those pages in sync
when changing loaders or evaluation semantics. Use the current implementation
and tests as the source of truth; do not infer supported fields from UI labels.

When changing documentation or examples, validate all complete YAML examples
through `load_scenario` (or CLI `--check` via a Profile), check JSON through
`load_profile`, resolve relative links and heading anchors, and review examples
against the intended branch. `--check` does not validate live input/ROI compatibility;
use frame-based tests for that. See [testing](testing.md#validating-documentation-examples).
