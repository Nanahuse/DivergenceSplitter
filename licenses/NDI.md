# NDI®ランタイムの通知

[日本語（正本）](NDI.md) | [English](NDI.en.md)

NDI®はVizrt NDI ABの登録商標です。[NDI公式サイト](https://ndi.video/)。

DivergenceSplitterのソースコードはMITライセンスです。一方、NDI対応Windows ZIPに入っているNDIランタイムはプロプライエタリなソフトウェアで、別のライセンスが適用されます。

- `Processing.NDI.Lib.x64.dll`：実行ファイルのディレクトリから読み込みます。
- `Processing.NDI.Lib.Licenses.txt`：変更せず同梱する、ランタイムの第三者通知です。
- [NDI-TERMS.txt](NDI-TERMS.txt)：SDK契約書3(d)項の要件を含む、同梱コンポーネントの利用条件です。

SDK契約書PDFはビルド時に存在とSHA-256を確認するために使い、配布物には含めません。契約書は[公式NDI SDK License Agreement](https://ndi.link/ndisdk_license)を参照してください。SDKヘッダー、インポートライブラリ、インストーラー、サンプル、NDI Toolsも配布物に含めません。

SDK無効の開発ビルドには説明用の通知だけを含め、NDIバイナリやSDK契約書は含めません。

DivergenceSplitterのMITライセンスは、NDIのSDKやランタイムには適用されません。SDK、ランタイム、NDIプロトコルには、アプリのソースコードとは別の条件が適用されます。[公式契約書](https://ndi.link/ndisdk_license)と[公式ライセンス要件](https://docs.ndi.video/all/developing-with-ndi/sdk/licensing)を参照してください。

標準SDKライセンスの対象は契約で定義される汎用コンピューター製品です。対象外の専用機器、制限されたホスト環境、組み込み機器には別の商用契約が必要です。配布時はリリース前に最新版SDKの要件を確認してください。固定値の更新時は実際に取得した契約書を確認し、未解決の義務があるままランタイムZIPを公開しないでください。

SDKのインストーラーと開発用ファイルは契約上の機密情報です。CIは信頼できる実行ごとに公式配布元から取得し、公開Actionsキャッシュへの保存や開発素材のアップロードを行いません。

[公式契約書](https://ndi.link/ndisdk_license)。[NDI Tools](https://ndi.video/tools/)は別途取得できます。
