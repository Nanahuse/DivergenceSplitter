# Developer guide

[日本語（正本）](README.md) | [English](README.en.md)

[Documentation home](../../README.en.md)

| Task | Guide |
| --- | --- |
| Understand component boundaries, threads, and control flow | [Architecture](architecture.en.md) |
| Configure CMake, dependencies, Qt, and the NDI SDK | [Building](building.en.md) |
| Run CTest, real Bridge integration, and NDI checks | [Testing](testing.en.md) |
| Produce and verify the Windows ZIP and notices | [Distribution](distribution.en.md) |

Public configuration belongs in the [Profile reference](../configuration.en.md) and
[scenario reference](../scenarios/yaml-reference.en.md). Keep those pages in sync
when changing loaders or evaluation semantics. Use the current implementation
and tests as the source of truth; do not infer supported fields from UI labels.

Japanese `.md` files are authoritative; `.en.md` files are reference translations.
If they differ, follow Japanese. Update Japanese first, then the corresponding
English version. Check keys, values, code examples, and links in both languages.

When changing documentation or examples, validate all complete YAML examples
through `load_scenario` (or CLI `--check` via a Profile), check JSON through
`load_profile`, resolve relative links and heading anchors, and review examples
against the intended branch. `--check` does not validate live input/ROI compatibility;
use frame-based tests for that. See [testing](testing.en.md#validating-documentation-examples).
