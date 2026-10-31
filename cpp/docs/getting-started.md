# はじめに

[日本語（正本）](getting-started.md) | [English](getting-started.en.md)

[ドキュメント一覧](../README.md)

まず時間だけで動作するシナリオを使い、画像判定の調整前に接続を確認します。このサンプルは開始条件の評価を始めて2秒後にLiveSplitを開始し、最初の区間の評価を始めて3秒後にSplitします。テスト中は映像が届く状態を保ってください。

## ダウンロードと起動

1. [C++23のActions](https://github.com/Nanahuse/DivergenceSplitter/actions/workflows/cpp23.yml)を開きます。使いたいリビジョンの信頼できる実行を選び、成功した実行から `DivergenceSplitter-cpp23-windows-x64` アーティファクトをダウンロードしてください。GitHubへのサインインが必要です。アーティファクトの有無はNDI有効ジョブの成功と保存期間によります。利用できるものがなければ[ソースからビルド](development/building.md)してください。
2. アーティファクトを展開し、その中のアプリケーションZIPも書き込み可能なローカルフォルダーに展開します。DLL、プラグインのフォルダー、ライセンスを同じ構成で保ってください。公式ZIPにはNDIランタイムを同梱しているため、SDKのインストールは不要です。
3. `DivergenceSplitter.exe` を起動します。初回は有効な入力がありません。前回のProfileとして記憶されたファイルが存在する場合、起動時に自動で開いて適用します。そのProfileのシナリオは入力とBridgeの準備が整うとLiveSplitを操作し始めることがあります。

## LiveSplit.Bridgeへの接続

1. LiveSplitと、Protocol v4に対応するLiveSplit.Bridgeを用意します。[Bridgeの導入手順](https://github.com/Nanahuse/LiveSplit.Bridge#インストール)に従い、LiveSplitを終了してからリリースZIP内の `LiveSplit.Bridge.dll` を `Components` に配置します。LiveSplitを開き直し、Edit Layout...でControl > LiveSplit Bridgeを追加してレイアウトを保存してください。
2. Bridgeの設定を開き、WebSocketポートを `54000` にします。StatusがRunningであることを確認してください。DivergenceSplitterは同じPCのLiveSplitに接続します。
3. LiveSplitに1区間のテスト用Runを作成して保存し、タイマーを停止状態にしておきます。以降の操作では実際にタイマーを制御するため、テスト用のRunを使ってください。

## 入力とシナリオの設定

1. このリビジョンの [minimal-scenario.yaml](../examples/minimal-scenario.yaml) をダウンロードし、分かる場所に保存します。例は `C:/DivergenceSplitter/minimal-scenario.yaml` です。
2. Profileを開き、次のいずれかの入力を選びます。
   - Camera：Detect camerasを押し、カメラまたはキャプチャーカードと列挙されたモードを選びます。このテストではRequest 60 fpsをオフにします。
   - Video file：10秒より長い再生可能なローカル録画を選びます。対応コーデックはビルドによります。最初の確認にはMJPEGのAVI録画を使えます。Profileを適用すると再生が始まります。
   - NDI®：送信元を起動し、Search againで公開名を選びます。NDI対応ビルドが必要です。
3. Crop marginsとResizeはオフにします。Add instanceで行を追加し、Bridge portを `54000` にします。行を選択してBrowse scenario...から保存したYAMLを指定してください。このテストでは余分な行を削除します。
4. Applyを押します。入力とシナリオの評価が始まります。アプリ内で別のStart操作をする必要はありません。

## 最初の自動Splitの確認

1. Monitorを開きます。プレビューが更新され、フレーム数が増え、インスタンスがReadyになることを確認してください。
2. 評価可能になって約2秒後にLiveSplitが開始し、さらに約3秒後に最初のSplitが実行されて1区間のRunが終了します。時刻は映像の到着とBridgeの準備に左右されます。Applyを押した瞬間からの待ち時間ではありません。
3. Diagnosticsを開き、Start、Splits、Conditionの状態やスコアを確認します。このサンプルは `elapsed` を使うため、参照画像とスコアのしきい値は不要です。
4. File > Save Profile As...でProfileを保存します。保存と適用は別の操作です。[利用ガイド](user-guide.md)を参照してください。

映像が届き続けている場合、このサンプルはタイマーのReset後に再び開始します。テストを終えたらアプリを閉じてください。ゲーム用の判定には[画像検出の例](scenarios/examples.md)を使い、問題がある場合は[トラブルシューティング](troubleshooting.md)を参照してください。
