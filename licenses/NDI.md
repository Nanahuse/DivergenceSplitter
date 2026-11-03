# NDI®ランタイムの通知

[日本語（正本）](NDI.md) | [English](NDI.en.md)

NDI®はVizrt NDI ABの登録商標です。[NDI公式サイト](https://ndi.video/)。

DivergenceSplitter自身のコードはMITライセンスです。NDI対応Windows ZIPには、個別のライセンスが適用されるプロプライエタリなNDIランタイムを追加で含みます。

- `Processing.NDI.Lib.x64.dll`：実行ファイルのディレクトリから読み込みます。
- `Processing.NDI.Lib.Licenses.txt`：変更せず同梱する、ランタイムの第三者通知です。
- [NDI-TERMS.txt](NDI-TERMS.txt)：SDK契約書3(d)項の要件を含む、同梱コンポーネントの利用条件です。

SDK契約書PDFはビルド時の存在・SHA-256検査にだけ使い、同梱しません。[公式NDI SDK License Agreement](https://ndi.link/ndisdk_license)を参照してください。SDKヘッダー、インポートライブラリ、インストーラー、サンプル、NDI Toolsは除外します。SDK無効の開発ビルドには説明用の通知は含みますが、NDIバイナリとSDK契約書は含みません。

SDKとランタイムをMITとして再ライセンスするものではありません。SDK、ランタイム、NDIプロトコルの条件は、DivergenceSplitterのソースとは別に適用されます。[公式契約書](https://ndi.link/ndisdk_license)と[公式ライセンス要件](https://docs.ndi.video/all/developing-with-ndi/sdk/licensing)を参照してください。

標準SDKライセンスの対象は契約で定義される汎用コンピューター製品です。対象外の専用機器、制限されたホスト環境、組み込み機器には別の商用契約が必要です。配布時はリリース前に最新版SDKの要件を確認してください。固定値の更新時は実際に取得した契約書を確認し、未解決の義務があるままランタイムZIPを公開しないでください。

SDKのインストーラーと開発用ファイルは契約上の機密情報です。CIは信頼できる実行ごとに公式配布元から取得し、公開Actionsキャッシュへの保存や開発素材のアップロードを行いません。

[公式契約書](https://ndi.link/ndisdk_license)。[NDI Tools](https://ndi.video/tools/)は別途取得できます。
