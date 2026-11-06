# NDI®ランタイムの通知

[日本語（正本）](NDI.md) | [English](NDI.en.md)

NDI®はVizrt NDI ABの登録商標です。NDI公式サイトは https://ndi.video/ です。

DivergenceSplitterのソースコードはMITライセンスです。NDI入力を使用する場合、NDI Runtimeを別途インストールする必要があります。NDI Runtimeはプロプライエタリなソフトウェアで、DivergenceSplitterのMITライセンスとは別の条件が適用されます。

- DivergenceSplitterの配布ZIPは `Processing.NDI.Lib.x64.dll` を同梱しません。
- NDI RuntimeはNDI公式サイトから利用者がインストールします。アプリはインストール済みRuntimeを起動時に検出します。
- Runtimeが見つからない場合、NDI入力だけが利用できません。Camera・Video入力とその他の機能は通常どおり動作します。
- Runtimeのライセンス条件と第三者の通知は、インストールしたRuntimeに含まれるものを確認してください。
- [NDI-TERMS.txt](NDI-TERMS.txt) は、NDI Runtimeを別途利用する場合に適用される条件の説明です。

SDK契約書PDF、SDKヘッダー、インポートライブラリ、インストーラー、サンプル、NDI Toolsは配布ZIPに含めません。契約条件は[公式NDI SDK License Agreement](https://ndi.link/ndisdk_license)を参照してください。

DivergenceSplitterのMITライセンスは、NDIのSDKやランタイムには適用されません。SDK、ランタイム、NDIプロトコルには、アプリのソースコードとは別の条件が適用されます。[公式契約](https://ndi.link/ndisdk_license)と[公式ライセンス要件](https://docs.ndi.video/all/developing-with-ndi/sdk/licensing)を参照してください。

標準SDKライセンスの対象は契約で定義される汎用コンピューター製品です。対象外の専用機器、制限されたホスト環境、組み込み機器には別の商用契約が必要です。配布者はリリース前に最新のSDK要件を確認してください。

SDKのインストーラーと開発用ファイルは契約上の機密情報です。CIは信頼できる実行ごとに公式配布元から取得し、公開Actionsキャッシュへの保存や開発素材のアップロードを行いません。

[公式契約](https://ndi.link/ndisdk_license)、[NDI Tools](https://ndi.video/tools/)は別途取得できます。
