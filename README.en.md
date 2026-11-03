# DivergenceSplitter

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

## Installation

Download the `DivergenceSplitter-cpp23-windows-x64` artifact from a successful
[C++23 Actions run](https://github.com/Nanahuse/DivergenceSplitter/actions/workflows/cpp23.yml).
GitHub sign-in is required. Extract the artifact and then the Windows ZIP inside
it into a writable directory. Keep the DLLs, plugins, and licenses alongside
`DivergenceSplitter.exe`. Availability depends on a successful NDI-enabled job and
artifact retention; otherwise [build from source](docs/development/building.en.md).
See [Getting started](docs/getting-started.en.md) for the initial setup.

## Usage

1. Install a Protocol v4-compatible LiveSplit.Bridge in LiveSplit and prepare a test run.
2. In Profile, select the video input, YAML scenario, and Bridge port.
3. Use Draft input preview to check Crop/Resize, then press Apply. Scenario
   evaluation and timer controls begin when input and Bridge are ready.
4. Inspect Monitor and Diagnostics, then save the Profile.

See the [user guide](docs/user-guide.en.md) and [samples](examples/README.en.md)
for detailed workflows and configuration examples.

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

## Development

The repository root is the CMake project. `src/` holds implementations, `include/`
holds interfaces shared between targets, `tests/` holds verification, `docs/`
holds documentation, and `tools/` holds Python build/distribution helpers.
See the [developer guide](docs/development/README.en.md) for builds, CTest,
Bridge TestHost integration, NDI, and Windows ZIP verification.

## License

Application source: [MIT](LICENSE). Bundled dependencies have separate licenses;
see the [distribution notice](DISTRIBUTION-NOTICE.txt) and
[distribution guide](docs/development/distribution.en.md).

NDI® is a registered trademark of Vizrt NDI AB. [NDI website](https://ndi.video/).
NDI-enabled distributions include a separately licensed runtime; see
[NDI notices](licenses/NDI.en.md).
