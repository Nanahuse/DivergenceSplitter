# Windows distribution

[Developer guide](README.md) · [Build setup](building.md) · [Testing](testing.md)

## Build and verify a ZIP

From `cpp/` in x64 Developer PowerShell with the prerequisites installed:

```powershell
cmake --preset full-release
cmake --build --preset full-release --parallel
ctest --preset full-release --output-on-failure
cmake --build build/full-release --target package
python tools/verify_windows_zip.py --build-dir build/full-release --ndi OFF
```

This default development build has NDI disabled. For an NDI-enabled distribution,
configure with the [NDI options](building.md#ndi-enabled-builds), build/test/package
the same preset, and pass `--ndi ON` to verification. Use a separate build directory
when switching SDK/dependency configurations. The verifier expects exactly one
ZIP in that directory.

CPack writes `DivergenceSplitter-<version>-windows-x64.zip` without an enclosing
top-level directory. Extract the entire ZIP to run it. The GUI distribution
contains `DivergenceSplitter.exe`, `divergencesplitter-cli.exe`, runtime DLLs,
Qt plugins, `LICENSE.txt`, `DISTRIBUTION-NOTICE.txt`, and `licenses/`.
The current install rules do not bundle documentation or sample scenarios; users
obtain those from the matching source revision.

The verifier extracts the ZIP and checks required executables/notices, SDK
exclusions, CLI `--help`, and GUI `--smoke-test`. It removes Qt/NDI lookup
environment variables and restricts PATH to the ZIP and Windows system directories.
For ON it also checks pinned runtime/notice hashes and initializes the local NDI
DLL with `--ndi-check`. Startup verification does not prove live input reception.

## CI workflow

[`C++23`](../../../.github/workflows/cpp23.yml) runs on pull requests, `main` pushes,
and manual dispatch. It uses Windows, MSVC, Ninja, vcpkg, externally installed
Qt 6.8.3, and the `ci` preset. It builds the pinned Bridge TestHost, runs CTest and
real TestHost integration, packages the ZIP, and verifies the extracted result.

- Fork PRs build NDI OFF and do not receive the SDK Secret.
- Same-repository PRs, main pushes, and manual runs require both OFF and ON jobs.
  An unavailable SDK does not silently fall back to OFF.
- The ON job requires repository Secret `NDI_SDK_URL_WINDOWS` containing the
  official Windows SDK download URL. It invokes
  [`get_ndi_sdk.py`](../../tools/get_ndi_sdk.py), which downloads using `curl.exe`,
  checks the pinned installer SHA-256, version, Authenticode publisher, extracted
  headers/runtime/notices/agreement, and writes `NDI_SDK_DIR` to the job environment.
  Download errors/timeouts fail and remove partial downloads; URL/captured curl
  output is not printed in the job log.
- [`ndi-sdk-lock.json`](../../tools/ndi-sdk-lock.json) records the reviewed SDK
  6.3.2.0 and innoextract 1.9 hashes. SDK files are never stored in public Actions
  caches. The vcpkg cache contains dependency downloads/binaries, not the SDK.
- Only ON uploads `DivergenceSplitter-cpp23-windows-x64`. Both variants upload
  their JUnit CTest results. Pushes to temporary work branches are not a workflow
  trigger; PRs and manual dispatch provide the checks.

## Third-party notices

Application source is [MIT](../../LICENSE). The package's
[`DISTRIBUTION-NOTICE.txt`](../../DISTRIBUTION-NOTICE.txt) identifies bundled/linked
dependencies, including Qt, OpenCV, Boost, yaml-cpp, nlohmann/json, the Bridge
client, and the camera-enumeration adaptation. Their licenses remain separate.

At install/package time,
[`collect_licenses.py`](../../tools/collect_licenses.py) gathers actual installed
vcpkg notices and the fetched Bridge license. It also retrieves the camera
adaptation's upstream license and external Qt 6.8.3 license texts from pinned
upstream commits using
[`third-party-license-lock.json`](../../tools/third-party-license-lock.json).
Downloaded texts remain in the ignored build cache. Missing notices, unsupported
external Qt versions, or changed pinned contents fail packaging. Transitive
dependency notices are included under `licenses/vcpkg/`.

Do not replace license bodies with short summaries. When updating dependencies,
verify the collected package notices as well as the build. The distribution's
license files are the authoritative notices for that ZIP.

## NDI runtime contents

NDI® is a registered trademark of Vizrt NDI AB. [NDI website](https://ndi.video/).
An ON ZIP additionally carries `Processing.NDI.Lib.x64.dll`, its unmodified
`Processing.NDI.Lib.Licenses.txt`, and application-maintained
[`licenses/NDI-TERMS.txt`](../../licenses/NDI-TERMS.txt).

The SDK agreement PDF is checked during configuration/acquisition but is not
packaged. SDK headers, import libraries, installers, sample senders, and NDI Tools
are excluded; the verifier rejects SDK development materials. OFF packages contain
explanatory notices but no NDI DLL.

For the runtime's separate terms and official licensing/distribution references,
read [`licenses/NDI.md`](../../licenses/NDI.md). Keep the trademark notice, website
link, runtime notices, and use terms with an NDI-enabled package. Updating the SDK
pin requires review of the actual agreement and redistribution requirements,
including the latest-SDK requirement, before publishing another runtime ZIP.
