# DivergenceSplitter

[日本語](README.md) | [English (Translation)](README.en.md)

This is an English translation. The Japanese version is the original and takes priority if there are differences.

DivergenceSplitter is a Windows desktop application that analyzes video and
automatically controls LiveSplit through LiveSplit.Bridge. YAML scenarios define
when to start, split, reset, and perform other timer actions.

User documentation is available in Japanese and English. Developer, design, build,
test, CI, distribution, and verification documents are available only in Japanese.
Configuration keys, UI labels, and file paths retain their implementation names.

- Native Dear ImGui interface with a live monitor and condition summaries.
- Camera / capture card input through DirectShow or Media Foundation, local video
  files supported by OpenCV, and NDI® network sources when the NDI Runtime is installed.
- Crop and resize processing, nine image detectors, and stateful conditions.
- One shared input feeding independent scenarios and LiveSplit instances.
- About lists bundled third-party components and additional license notices.

## Installation

Download `DivergenceSplitter-<version>-windows-x64.zip` from a successful
[C++23 Actions run](https://github.com/Nanahuse/DivergenceSplitter/actions/workflows/cpp23.yml).
GitHub sign-in is required. Extract the ZIP into a writable directory.
Keep the DLLs and licenses alongside
`DivergenceSplitter.exe`. Availability depends on a successful Windows job and
artifact retention; otherwise [build from source (Japanese)](docs/development/building.md).
See [Getting started](docs/getting-started.en.md) for the initial setup.

## Usage

1. Install a Protocol v4-compatible LiveSplit.Bridge in LiveSplit and prepare a test run.
2. In Profile, select the video input, YAML scenario, and Bridge port.
3. Use Draft input preview to check Crop/Resize, then press Apply. Scenario
   evaluation and timer controls begin when input and Bridge are ready.
4. Inspect Monitor, then save the Profile.

See the [user guide](docs/user-guide.en.md) and [samples](examples/README.en.md)
for detailed workflows and configuration examples.

## Documentation

| I want to… | Read |
| --- | --- |
| Install and make my first automatic split | [Getting started](docs/getting-started.en.md) |
| Use Monitor, Profile, Settings, and About | [User guide](docs/user-guide.en.md) |
| Configure inputs, transforms, and Bridge ports | [Configuration reference](docs/configuration.en.md) |
| Diagnose input, connection, or detection problems | [Troubleshooting](docs/troubleshooting.en.md) |
| Write a scenario | [Scenario authoring](docs/scenarios/README.en.md) |
| Look up YAML, conditions, detectors, or actions | [YAML reference](docs/scenarios/yaml-reference.en.md), [conditions](docs/scenarios/conditions.en.md), [detectors](docs/scenarios/detectors.en.md) |
| Adapt working patterns | [Scenario examples](docs/scenarios/examples.en.md), [sample files](examples/README.en.md) |
| Build, test, or distribute the application | [Developer guide (Japanese)](docs/development/README.md) |

## Development

The repository root is the CMake project. `src/` holds implementations, `include/`
holds interfaces shared between targets, `tests/` holds verification, `docs/`
holds documentation, and `tools/` holds Python build/distribution helpers.
See the [developer guide (Japanese)](docs/development/README.md) for builds, CTest,
Bridge TestHost integration, NDI, and Windows ZIP verification.

## License

Application source: [MIT](LICENSE). Bundled dependencies have separate licenses;
see the [distribution notice](DISTRIBUTION-NOTICE.txt) and
[distribution guide (Japanese)](docs/development/distribution.md).

NDI® is a registered trademark of Vizrt NDI AB. [NDI website](https://ndi.video/).
NDI input requires a separately installed runtime; the distribution does not
bundle it. See [NDI notices](licenses/NDI.en.md).
