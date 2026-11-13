# DivergenceSplitter

## 目次

- [できること](#できること)
- [インストール](#インストール)
- [ドキュメント](#ドキュメント)
- [ライセンス](#ライセンス)

## できること

DivergenceSplitterは、映像を判定し、LiveSplitのStart、Split、Resetなどを自動で行うWindowsアプリです。LiveSplitとの接続には、Protocol v4対応のLiveSplit.Bridgeを使います。

- カメラ、キャプチャーカード、動画ファイル、NDI®の映像を使えます。入力映像の切り取り（Crop）とサイズ変更（Resize）も設定できます。
- 画像を調べるDetectorと、スコアや経過時間を判定するConditionを組み合わせて、YAMLでシナリオを作れます。
- 1つの映像を複数のシナリオで判定し、それぞれ別のLiveSplitを操作できます。Monitorで映像、接続状態、判定結果を確認できます。

## インストール

1. GitHubにサインインし、[GitHub ActionsのCI](https://github.com/Nanahuse/DivergenceSplitter/actions/workflows/ci.yml)を開きます。
2. 使いたいリビジョンで `Windows x64` ジョブが成功した実行を選び、Artifactsから `DivergenceSplitter-<version>-windows-x64.zip` をダウンロードします。保存期間が過ぎたファイルはダウンロードできません。
3. ZIPを書き込み可能なフォルダーに展開し、`DivergenceSplitter.exe` を起動します。同梱のDLLとライセンスファイルは展開時の配置を保ってください。

NDI入力を使う場合は、[NDI Runtime](https://ndi.video/)もインストールしてください。配布ZIPには含まれていません。

起動したら、[はじめに](docs/getting-started.md)の手順でLiveSplitを接続し、自動Splitを試してください。

## ドキュメント

| 目的 | 参照先 |
| --- | --- |
| LiveSplitを接続して最初の自動Splitを試す | [はじめに](docs/getting-started.md) |
| Monitorで判定を確認する、Profileを編集・保存する | [利用ガイド](docs/user-guide.md) |
| Profileとアプリ設定のJSONを調べる | [設定リファレンス](docs/configuration.md) |
| 映像・接続・判定の問題を解決する | [トラブルシューティング](docs/troubleshooting.md) |
| 自分のゲームに合わせてシナリオを作る | [シナリオ作成](docs/scenarios/README.md) |
| シナリオの項目と実行時の動作を調べる | [YAML](docs/scenarios/yaml-reference.md)、[Condition](docs/scenarios/conditions.md)、[Detector](docs/scenarios/detectors.md) |
| サンプルを試す、用途に合う設定例を探す | [サンプルファイル](examples/README.md)、[シナリオ例](docs/scenarios/examples.md) |

## ライセンス

ソースコードには[MITライセンス](LICENSE)が適用されます。同梱する第三者コンポーネントには、それぞれのライセンスが適用されます。アプリのAbout画面または[配布時の通知](DISTRIBUTION-NOTICE.txt)を参照してください。

NDI®はVizrt NDI ABの登録商標です。利用条件は[NDIの通知](licenses/NDI.md)を参照してください。
