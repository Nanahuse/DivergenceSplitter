# DivergenceSplitter

[日本語（正本）](README.md) | [English](README.en.md)

DivergenceSplitterは、映像の変化を検出してLiveSplitの開始やSplit、Resetを自動で行うWindowsアプリです。判定条件はYAMLファイルに記述します。画面から入力映像や判定結果を確認できます。

## 主な機能

- カメラ・キャプチャーカード、動画ファイル、NDI®の映像を入力に使えます。NDI入力を使用するには、NDI Runtimeを別途インストールする必要があります。
- 映像の切り取り（Crop）やサイズ変更（Resize）を行い、画像の検出方法（Detector）と条件（Condition）を組み合わせて判定できます。
- 条件が成立すると、LiveSplit.Bridgeを通じてStart、Split、Resetなどの操作を送ります。
- 1つの映像を複数のシナリオで判定し、それぞれ別のLiveSplitを操作できます。画面には映像のプレビューと判定・接続の状態を表示します。
- About画面に、同梱する第三者コンポーネントと追加のライセンス通知一覧を表示します。

## インストール

[C++23のGitHub Actions](https://github.com/Nanahuse/DivergenceSplitter/actions/workflows/cpp23.yml)を開き、使いたいリビジョンで成功した実行結果から `DivergenceSplitter-<version>-windows-x64.zip` をダウンロードしてください。ダウンロードにはGitHubへのサインインが必要です。

ダウンロードしたZIPを書き込み可能なフォルダーへ展開し、`DivergenceSplitter.exe` を起動します。DLLとライセンスのファイルは、展開後の配置を保ってください。

ダウンロードできるのは、Windowsジョブが成功し、アーティファクトの保存期間が切れていない場合です。利用できる実行結果がなければ、[ソースからビルド](docs/development/building.md)してください。最初の設定は[はじめに](docs/getting-started.md)で説明します。

## 使い方

1. LiveSplitにProtocol v4対応のLiveSplit.Bridgeを導入し、テスト用Runを用意します。
2. Profileで映像入力、YAMLシナリオ、Bridgeポートを設定します。
3. Draft input previewで映像とCrop／Resizeの結果を確認し、Applyを押します。入力とBridgeの準備が整うとシナリオの評価とタイマー操作が始まります。
4. Monitorで判定・接続状態を確認し、Profileを保存します。

具体的な操作と設定例は[利用ガイド](docs/user-guide.md)と[サンプル](examples/README.md)にあります。

## ドキュメント

利用者向けの文書には日本語版と英語版があります。日本語版を正本とし、英語版はその翻訳です。内容が異なる場合は日本語版に従ってください。画面名、設定キー、ファイルパスは、どちらの言語でも製品の表記に合わせています。

開発・設計・ビルド・テスト・CI・配布の手順と検証記録は、日本語のみで提供します。

| 目的 | 参照先 |
| --- | --- |
| 導入して最初の自動Splitを試す | [はじめに](docs/getting-started.md) |
| Monitor、Profile、Settings、Aboutを使う | [利用ガイド](docs/user-guide.md) |
| 入力、画像変換、Bridge接続を設定する | [設定リファレンス](docs/configuration.md) |
| 入力・接続・判定の問題を調べる | [トラブルシューティング](docs/troubleshooting.md) |
| シナリオを作る | [シナリオ作成](docs/scenarios/README.md) |
| YAML、Condition、Detector、Actionの仕様を調べる | [YAML](docs/scenarios/yaml-reference.md)、[Condition](docs/scenarios/conditions.md)、[Detector](docs/scenarios/detectors.md) |
| 設定例を応用する | [シナリオ例](docs/scenarios/examples.md)、[サンプルファイル](examples/README.md) |
| ビルド、テスト、配布を行う | [開発ガイド](docs/development/README.md) |

## 開発

アプリはC++23とDear ImGui（Win32 / Direct3D 11）で実装しています。CMakeの設定はリポジトリ直下にあります。実装は `src/`、複数のターゲットで共有するヘッダーは `include/`、テストは `tests/`、文書は `docs/` に置きます。`tools/` にはPythonで書いたビルド・配布用の補助スクリプトがあります。

ビルド、CTest、Bridge TestHostとの結合テスト、NDI、Windows ZIPの作成と検証は、[開発ガイド](docs/development/README.md)を参照してください。

## ライセンス

ソースコードは[MITライセンス](LICENSE)です。同梱する依存ライブラリにはそれぞれ別のライセンスが適用されます。[配布時の通知](DISTRIBUTION-NOTICE.txt)と[第三者ライセンスの収集・配布手順](docs/development/distribution.md)を参照してください。

NDI®はVizrt NDI ABの登録商標です。[NDI公式サイト](https://ndi.video/)。NDI入力を使用する場合、NDI Runtimeを別途インストールする必要があります。配布ZIPには同梱されません。条件は[NDIの通知](licenses/NDI.md)を参照してください。
