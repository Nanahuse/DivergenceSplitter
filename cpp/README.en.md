# DivergenceSplitter C++23

[日本語（正本）](README.md) | [English](README.en.md)

DivergenceSplitter is a Windows desktop application that analyzes video and
automatically controls LiveSplit through LiveSplit.Bridge. YAML scenarios define
when to start, split, reset, and perform other timer actions.

The Japanese documents are authoritative. English is a reference translation;
if the versions differ, follow the Japanese version. Configuration keys, UI labels,
and commands retain their implementation names.

- Native Qt interface with a live monitor and condition diagnostics.
- Camera / capture card input through DirectShow or Media Foundation, local video
  files supported by OpenCV, and NDI® network sources in NDI-enabled builds.
- Crop and resize processing, nine image detectors, and stateful conditions.
- One shared input feeding independent scenarios and LiveSplit instances.
- A headless command-line runner for validation and automated checks.

## Documentation

| I want to… | Read |
| --- | --- |
| Install and make my first automatic split | [Getting started](docs/getting-started.en.md) |
| Use Monitor, Profile, Diagnostics, and Settings | [User guide](docs/user-guide.en.md) |
| Configure inputs, transforms, and Bridge ports | [Configuration reference](docs/configuration.en.md) |
| Diagnose input, connection, or detection problems | [Troubleshooting](docs/troubleshooting.en.md) |
| Write a scenario | [Scenario authoring](docs/scenarios/README.en.md) |
| Look up YAML, conditions, detectors, or actions | [YAML reference](docs/scenarios/yaml-reference.en.md), [conditions](docs/scenarios/conditions.en.md), [detectors](docs/scenarios/detectors.en.md) |
| Adapt working patterns | [Scenario examples](docs/scenarios/examples.en.md), [sample files](examples/README.en.md) |
| Build, test, or distribute the application | [Developer guide](docs/development/README.en.md) |

## License

Application source: [MIT](LICENSE). Bundled dependencies have separate licenses;
see the [distribution notice](DISTRIBUTION-NOTICE.txt) and
[distribution guide](docs/development/distribution.en.md).

NDI® is a registered trademark of Vizrt NDI AB. [NDI website](https://ndi.video/).
NDI-enabled distributions include a separately licensed runtime; see
[NDI notices](licenses/NDI.en.md).
