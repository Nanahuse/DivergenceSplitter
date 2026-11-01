# DivergenceSplitter

DivergenceSplitterは、映像を解析してLiveSplitを自動操作するWindowsアプリケーションです。C++23で実装し、Qt Widgetsの画面とCLIを備えています。

## 主な機能

- カメラ・キャプチャーカード、動画ファイル、NDI対応ビルドでのNDI®入力。
- Crop／Resizeと画像Detector、Conditionを組み合わせたYAMLシナリオの判定。
- LiveSplit.Bridgeを通じたStart、Split、Resetなどの操作。
- 複数のシナリオ・LiveSplitインスタンスでの入力共有と、画面でのプレビュー・診断。

## インストール

[C++23のGitHub Actions](https://github.com/Nanahuse/DivergenceSplitter/actions/workflows/cpp23.yml)で、使いたいリビジョンの成功した実行から `DivergenceSplitter-cpp23-windows-x64` アーティファクトを取得します。GitHubへのサインインが必要です。展開後、中のWindows ZIPも書き込み可能なフォルダーに展開し、`DivergenceSplitter.exe` を起動してください。DLL、プラグイン、ライセンスは同じ構成で保ちます。

アーティファクトの提供はNDI有効ジョブの成功と保存期間によります。取得できない場合は[ソースからビルド](cpp/docs/development/building.md)してください。詳しい導入手順は[はじめに](cpp/docs/getting-started.md)を参照してください。

## 使い方

1. LiveSplitにProtocol v4対応のLiveSplit.Bridgeを導入し、テスト用Runを用意します。
2. Profileで映像入力、YAMLシナリオ、Bridgeポートを設定します。
3. Draft input previewで映像とCrop／Resizeの結果を確認し、Applyを押します。入力とBridgeの準備が整うとシナリオの評価とタイマー操作が始まります。
4. MonitorとDiagnosticsで判定・接続状態を確認し、Profileを保存します。

具体的な操作と設定例は[利用ガイド](cpp/docs/user-guide.md)と[サンプル](cpp/examples/README.md)にあります。

## ドキュメント

[C++23版ドキュメント一覧](cpp/README.md)から、設定リファレンス、シナリオ作成、トラブルシューティングへ進めます。`cpp/` 以下の日本語ドキュメントを正本とし、英語版は参考訳です。

## 開発

C++23版のソース、CMake構成、テストは `cpp/` にあります。[開発ガイド](cpp/docs/development/README.md)にビルド、CTest、Bridge TestHost結合試験、NDI、Windows ZIPの生成・検証をまとめています。

[AutoSplit変換ツール](tools/README.md)は、AutoSplitの設定と参照画像からYAMLを生成する独立した補助ツールです。Python 3.11以上とTkinterを使い、リポジトリのルートから `python tools/converter_entry.py` で起動します。C++版のビルド・配布にもPython補助スクリプトを使用します。

## ライセンス

ソースコードは[MITライセンス](LICENSE)です。同梱する依存ライブラリにはそれぞれ別のライセンスが適用されます。[配布時の通知](cpp/DISTRIBUTION-NOTICE.txt)と[第三者ライセンスの収集・配布手順](cpp/docs/development/distribution.md)を参照してください。

NDI®はVizrt NDI ABの登録商標です。[NDI公式サイト](https://ndi.video/)。NDI対応の配布物に同梱するランタイムの条件は[NDIの通知](cpp/licenses/NDI.md)を参照してください。
