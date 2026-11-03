# DivergenceSplitter

[日本語（正本）](README.md) | [English](README.en.md)

DivergenceSplitterは、映像を解析してLiveSplitを自動操作するWindowsアプリケーションです。C++23で実装し、Qt Widgetsの画面とCLIを備えています。

## 主な機能

- カメラ・キャプチャーカード、動画ファイル、NDI対応ビルドでのNDI®入力。
- Crop／Resizeと画像Detector、Conditionを組み合わせたYAMLシナリオの判定。
- LiveSplit.Bridgeを通じたStart、Split、Resetなどの操作。
- 複数のシナリオ・LiveSplitインスタンスでの入力共有と、画面でのプレビュー・診断。

## インストール

[C++23のGitHub Actions](https://github.com/Nanahuse/DivergenceSplitter/actions/workflows/cpp23.yml)で、使いたいリビジョンの成功した実行から `DivergenceSplitter-cpp23-windows-x64` アーティファクトを取得します。GitHubへのサインインが必要です。展開後、中のWindows ZIPも書き込み可能なフォルダーに展開し、`DivergenceSplitter.exe` を起動してください。DLL、プラグイン、ライセンスは同じ構成で保ちます。

アーティファクトの提供はNDI有効ジョブの成功と保存期間によります。取得できない場合は[ソースからビルド](docs/development/building.md)してください。詳しい導入手順は[はじめに](docs/getting-started.md)を参照してください。

## 使い方

1. LiveSplitにProtocol v4対応のLiveSplit.Bridgeを導入し、テスト用Runを用意します。
2. Profileで映像入力、YAMLシナリオ、Bridgeポートを設定します。
3. Draft input previewで映像とCrop／Resizeの結果を確認し、Applyを押します。入力とBridgeの準備が整うとシナリオの評価とタイマー操作が始まります。
4. MonitorとDiagnosticsで判定・接続状態を確認し、Profileを保存します。

具体的な操作と設定例は[利用ガイド](docs/user-guide.md)と[サンプル](examples/README.md)にあります。

## ドキュメント

製品ドキュメントは日本語版を正本とし、英語版は参考訳です。記述に差がある場合は日本語版に従ってください。設定キー、画面名、コマンドは実装上の表記を使います。

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

## 開発

リポジトリ直下がCMakeプロジェクトです。`src/` は実装、`include/` はターゲット間の共有インターフェース、`tests/` は検証、`docs/` は文書、`tools/` はビルド・配布補助を置きます。[開発ガイド](docs/development/README.md)にビルド、CTest、Bridge TestHost結合試験、NDI、Windows ZIPの生成・検証をまとめています。ビルド・配布の補助スクリプトにはPythonを使用します。

## ライセンス

ソースコードは[MITライセンス](LICENSE)です。同梱する依存ライブラリにはそれぞれ別のライセンスが適用されます。[配布時の通知](DISTRIBUTION-NOTICE.txt)と[第三者ライセンスの収集・配布手順](docs/development/distribution.md)を参照してください。

NDI®はVizrt NDI ABの登録商標です。[NDI公式サイト](https://ndi.video/)。NDI対応の配布物に同梱するランタイムの条件は[NDIの通知](licenses/NDI.md)を参照してください。
