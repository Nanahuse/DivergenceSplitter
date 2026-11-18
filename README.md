# DivergenceSplitter

DivergenceSplitter は、映像をもとに LiveSplit の Start、Split、Reset などを自動で行う Windows アプリです。カメラ、キャプチャーカード、動画ファイル、NDI® の映像を使えます。LiveSplit との接続にはProtocol v4 対応の LiveSplit.Bridge を使います。

同梱の Scenario Builder ではどの場面でタイマーを操作するかを画面から設定できます。たとえば、ゲームのクリア画面が映ったときに Split する設定を作れます。

## インストール

1. [GitHub Releases](https://github.com/Nanahuse/DivergenceSplitter/releases/latest) の Assets から `DivergenceSplitter-<version>-windows-x64.zip` をダウンロードします。
2. ZIP を書き込み可能なフォルダーに展開します。同梱ファイルは展開時の配置のまま使ってください。
3. シナリオを実行するには `DivergenceSplitter.exe`、作成・編集するには `ScenarioBuilder.exe` を起動します。

NDI 入力を使う場合は [NDI Runtime](https://ndi.video/) をインストールしてください。Scenario Builder の起動時に Microsoft Edge WebView2 Runtime のインストールを求められた場合は、画面の案内に従ってください。

## 使い方

| やりたいこと | 手順 |
| --- | --- |
| 映像と LiveSplit をつなぎ、最初の自動 Split を試す | [はじめに](docs/getting-started.md) |
| 自分のゲーム用のシナリオを作る | [Scenario Builder の使い方](docs/scenario-builder.md) |
| 複数の LiveSplit を操作する、判定結果を確認する、設定を保存する | [DivergenceSplitter の利用ガイド](docs/user-guide.md) |
| サンプルを使って設定や動作を確かめる | [サンプルシナリオ](examples/README.md) |
| 映像・接続・判定の問題を調べる | [トラブルシューティング](docs/troubleshooting.md) |

ソースからのビルドとテストの手順は[開発ガイド](docs/building.md)を参照してください。

## ライセンス

ソースコードには [MIT ライセンス](LICENSE) が適用されます。同梱する第三者コンポーネントには、それぞれのライセンスが適用されます。アプリの About 画面または[配布時の通知](DISTRIBUTION-NOTICE.txt)を参照してください。

NDI® は Vizrt NDI AB の登録商標です。利用条件は [NDI の通知](licenses/NDI.md)を参照してください。
