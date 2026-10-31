# DivergenceSplitter C++23

[日本語（正本）](README.md) | [English](README.en.md)

DivergenceSplitterは映像を解析し、LiveSplit.Bridgeを通じてLiveSplitを自動操作するWindowsアプリケーションです。開始、Split、Resetなどの実行条件をYAMLシナリオに記述します。

`cpp/` 以下の製品ドキュメントは日本語版を正本とします。英語版は参考訳です。記述に差がある場合は日本語版に従ってください。設定のキー、画面名、コマンドは実装上の表記を使います。

- Qtの画面で映像と判定の状態を確認できます。
- DirectShow／Media Foundationのカメラ・キャプチャーカード、OpenCVで再生できる動画ファイル、NDI対応ビルドでのNDI®入力に対応します。
- Crop／Resize、9種類のDetector、状態を持つConditionを組み合わせて判定できます。
- 1つの入力を複数のシナリオとLiveSplitインスタンスで共有できます。
- CLIで設定の検証や画面なしでの実行ができます。

## ドキュメント

| 目的 | 参照先 |
| --- | --- |
| 導入して最初の自動Splitを試す | [はじめに](docs/getting-started.md) |
| Monitor、Profile、Diagnostics、Settingsを使う | [利用ガイド](docs/user-guide.md) |
| 入力、画像変換、Bridge接続を設定する | [設定リファレンス](docs/configuration.md) |
| 入力・接続・判定の問題を調べる | [トラブルシューティング](docs/troubleshooting.md) |
| シナリオを作る | [シナリオ作成](docs/scenarios/README.md) |
| YAML、Condition、Detector、Actionの仕様を調べる | [YAML](docs/scenarios/yaml-reference.md)、[Condition](docs/scenarios/conditions.md)、[Detector](docs/scenarios/detectors.md) |
| 設定例を応用する | [シナリオ例](docs/scenarios/examples.md)、[サンプルファイル](examples/README.md) |
| ビルド、テスト、配布を行う | [開発ガイド](docs/development/README.md) |

## ライセンス

アプリケーションのソースコードは[MITライセンス](LICENSE)です。同梱する依存ライブラリには別のライセンスが適用されます。[配布時の通知](DISTRIBUTION-NOTICE.txt)と[配布ガイド](docs/development/distribution.md)を参照してください。

NDI®はVizrt NDI ABの登録商標です。[NDI公式サイト](https://ndi.video/)。NDI対応の配布物には、別のライセンスが適用されるランタイムを同梱します。[NDIの通知](licenses/NDI.md)を参照してください。
