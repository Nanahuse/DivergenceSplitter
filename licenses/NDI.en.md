# NDI® runtime notices

[日本語](NDI.md) | [English (Translation)](NDI.en.md)

This is an English translation. The Japanese version is the original and takes priority if there are differences.

NDI® is a registered trademark of Vizrt NDI AB. [NDI website](https://ndi.video/).

DivergenceSplitter's own code remains under its MIT License. NDI input requires
the NDI Runtime to be installed separately. The NDI Runtime is proprietary
software and is not covered by DivergenceSplitter's MIT License.

- The Windows distribution ZIP does not bundle `Processing.NDI.Lib.x64.dll`.
- Install the NDI Runtime separately from the official NDI website. The
  application detects an installed runtime at startup.
- If the runtime is not found, only NDI input is unavailable. Camera and video
  input and the rest of the application continue to work normally.
- Review the license terms and third-party notices included with the installed
  runtime.
- [NDI-TERMS.txt](NDI-TERMS.txt) describes the terms that apply when the NDI
  Runtime is used separately.

The SDK agreement PDF, SDK headers, import libraries, installers, examples and
NDI Tools are not included in the distribution ZIP. Read the
[official NDI SDK License Agreement](https://ndi.link/ndisdk_license).

The SDK/runtime is not relicensed under MIT. Its conditions apply to the SDK,
runtime and NDI protocols, separately from DivergenceSplitter's own source.
See the [official agreement](https://ndi.link/ndisdk_license) and
[official licensing requirements](https://docs.ndi.video/all/developing-with-ndi/sdk/licensing).

The standard SDK license is for its defined general-purpose computer Products;
excluded appliances, restricted hosted environments and embedded devices need
a separate commercial agreement. Distributors must check the latest-SDK
requirement before a release.

SDK installers and development files are confidential under the agreement.
CI downloads directly from the official source on every trusted run and never
stores the SDK in a public Actions cache or uploads development materials.

Official agreement: <https://ndi.link/ndisdk_license>.
NDI Tools are available separately at <https://ndi.video/tools/>.
