# DivergenceSplitter C++23

DivergenceSplitter is a Windows desktop application that analyzes video and
automatically controls LiveSplit through LiveSplit.Bridge. YAML scenarios define
when to start, split, reset, and perform other timer actions.

- Native Qt interface with a live monitor and condition diagnostics.
- Camera / capture card input through DirectShow or Media Foundation, local video
  files supported by OpenCV, and NDI® network sources in NDI-enabled builds.
- Crop and resize processing, nine image detectors, and stateful conditions.
- One shared input feeding independent scenarios and LiveSplit instances.
- A headless command-line runner for validation and automated checks.

## Documentation

| I want to… | Read |
| --- | --- |
| Install and make my first automatic split | [Getting started](docs/getting-started.md) |
| Use Monitor, Profile, Diagnostics, and Settings | [User guide](docs/user-guide.md) |
| Configure inputs, transforms, and Bridge ports | [Configuration reference](docs/configuration.md) |
| Diagnose input, connection, or detection problems | [Troubleshooting](docs/troubleshooting.md) |
| Write a scenario | [Scenario authoring](docs/scenarios/README.md) |
| Look up YAML, conditions, detectors, or actions | [YAML reference](docs/scenarios/yaml-reference.md), [conditions](docs/scenarios/conditions.md), [detectors](docs/scenarios/detectors.md) |
| Adapt working patterns | [Scenario examples](docs/scenarios/examples.md), [sample files](examples/README.md) |
| Build, test, or distribute the application | [Developer guide](docs/development/README.md) |

## License

Application source: [MIT](LICENSE). Bundled dependencies have separate licenses;
see the [distribution notice](DISTRIBUTION-NOTICE.txt) and
[distribution guide](docs/development/distribution.md).

NDI® is a registered trademark of Vizrt NDI AB. [NDI website](https://ndi.video/).
NDI-enabled distributions include a separately licensed runtime; see
[NDI notices](licenses/NDI.md).
