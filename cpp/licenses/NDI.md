# NDI® runtime notices

NDI® is a registered trademark of Vizrt NDI AB. [NDI website](https://ndi.video/).

DivergenceSplitter's own code remains under its MIT License. NDI-enabled Windows
ZIPs additionally contain the separately licensed proprietary NDI runtime:

- `Processing.NDI.Lib.x64.dll`, loaded from the executable directory;
- `Processing.NDI.Lib.Licenses.txt`, the unmodified runtime third-party notices;
- `licenses/ndi-sdk/`, the unmodified agreement from the selected official SDK;
- [NDI-TERMS.txt](NDI-TERMS.txt), the applicable bundled component use terms,
  including the requirements of SDK agreement section 3(d).

SDK headers, import libraries, installers, examples and NDI Tools are excluded.
An SDK-disabled development build contains these explanatory notices but no
NDI binaries or SDK agreement. No Python bindings are used by the C++ product.

The SDK/runtime is not relicensed under MIT. Its conditions apply to the SDK,
runtime and NDI protocols, separately from DivergenceSplitter's own source.
See the included agreement and [official licensing requirements](https://docs.ndi.video/all/developing-with-ndi/sdk/licensing).

The standard SDK license is for its defined general-purpose computer Products;
excluded appliances, restricted hosted environments and embedded devices need
a separate commercial agreement. Distributors must check the latest-SDK
requirement before a release. Review the actual downloaded agreement when
updating the pin; do not publish a runtime ZIP with unresolved obligations.

SDK installers and development files are confidential under the agreement.
CI downloads directly from the official source on every trusted run and never
stores the SDK in a public Actions cache or uploads development materials.

Official agreement: <https://ndi.link/ndisdk_license>.
NDI Tools are available separately at <https://ndi.video/tools/>.
