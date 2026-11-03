# はじめに

[日本語（正本）](getting-started.md) | [English](getting-started.en.md)

[ドキュメント一覧](../README.md)

ここでは、映像入力とLiveSplit.Bridgeへの接続を確認し、最初の自動Splitを試します。画像の検出は使わず、時間が経つと操作するサンプルシナリオを使います。

サンプルは開始条件の判定を始めて2秒後にStartし、最初の区間の判定を始めて3秒後にSplitします。判定には映像が必要なので、テスト中は映像が届く状態を保ってください。

## ダウンロードと起動

1. [C++23のActions](https://github.com/Nanahuse/DivergenceSplitter/actions/workflows/cpp23.yml)を開き、利用するリビジョンの信頼できる実行結果を選びます。成功した実行から `DivergenceSplitter-cpp23-windows-x64` をダウンロードしてください。GitHubへのサインインが必要です。NDI有効ジョブが成功していない場合や、保存期間が切れている場合は取得できません。その場合は[ソースからビルド](development/building.md)します。
2. ダウンロードしたファイルを展開し、中にあるアプリ本体のZIPも、書き込み可能なローカルフォルダーへ展開します。DLL、プラグインのフォルダー、ライセンスは、展開後の配置を保ってください。公式ZIPにはNDIランタイムが含まれているため、SDKをインストールする必要はありません。
3. `DivergenceSplitter.exe` を起動します。初回は映像入力が未設定です。以前に開いたProfileのファイルが残っていれば、起動時に自動で読み込んで適用します。その場合は、映像とBridgeの準備が整うと、保存済みのシナリオによるタイマー操作が始まることがあります。

## LiveSplit.Bridgeへの接続

1. LiveSplitと、Protocol v4に対応するLiveSplit.Bridgeを用意します。[Bridgeの導入手順](https://github.com/Nanahuse/LiveSplit.Bridge#インストール)に従い、LiveSplitを終了してからリリースZIP内の `LiveSplit.Bridge.dll` を `Components` に配置します。LiveSplitを開き直し、Edit Layout...でControl > LiveSplit Bridgeを追加してレイアウトを保存してください。
2. Bridgeの設定を開き、WebSocketポートを `54000` にします。StatusがRunningであることを確認してください。DivergenceSplitterは同じPCのLiveSplitに接続します。
3. LiveSplitに、1区間だけのテスト用Run（計測する区間の一覧）を作成して保存し、タイマーを停止状態にしておきます。以降の操作では実際にタイマーを制御するため、テスト用のRunを使ってください。

## 入力とシナリオの設定

1. 使用するアプリと同じリビジョンの [minimal-scenario.yaml](../examples/minimal-scenario.yaml) をダウンロードし、分かる場所に保存します。保存先の例は `C:/DivergenceSplitter/minimal-scenario.yaml` です。
2. Profileを開き、映像入力を選びます。
   - Camera：Detect camerasを押し、一覧からカメラまたはキャプチャーカードとモードを選びます。このテストではRequest 60 fpsをオフにします。
   - Video file：再生できるローカルの動画を選びます。テストには10秒より長い録画を使ってください。対応するコーデックはビルドによって異なりますが、最初の確認にはMJPEGのAVI録画を使えます。動画は下書きプレビューでも再生され、Applyすると先頭に戻ります。
   - NDI®：送信元を起動し、Search againを押して送信元の公開名を選びます。NDI対応ビルドが必要です。
3. Crop marginsとResizeをオフにします。Add instanceで行を追加し、Bridge portに `54000` を指定します。その行を選び、Browse scenario...から保存したYAMLを指定してください。このテストで使わない行は削除します。
4. Draft input previewのPreview inputを有効にし、映像が表示されることを確認します。入力の寸法、受信FPS、変換後の寸法も確認してください。シナリオを実行中の場合は、先にStop Session and preview draftで停止します。プレビューだけではシナリオの判定やLiveSplitの操作は行いません。入力エラーを修正してから次へ進んでください。詳しくは[下書きプレビュー](user-guide.md#入力の下書きプレビュー)を参照してください。
5. Applyを押します。映像の取得とシナリオの判定が始まります。DivergenceSplitter側で別にStartを押す必要はありません。

## 最初の自動Splitの確認

1. Monitorを開き、プレビューが更新されてフレーム数が増えることを確認します。LiveSplitに接続する行の状態がReadyになっていることも確認してください。
2. 判定できる状態になって約2秒後にLiveSplitが開始し、さらに約3秒後にSplitして、1区間のRunが終了します。開始時刻は映像の到着とBridgeの準備に左右されます。Applyを押した時刻から数えるわけではありません。
3. Diagnosticsを開き、Start、Splits、Conditionの状態を確認します。このサンプルの条件は `elapsed` なので、参照画像やスコアのしきい値を用意する必要はありません。
4. File > Save Profile As...でProfileを保存します。保存しても設定を適用したことにはなりません。保存とApplyの違いは[利用ガイド](user-guide.md)を参照してください。

映像が届き続けている場合、このサンプルはタイマーのReset後に再び開始します。テストを終えたらアプリを閉じてください。ゲーム用の判定には[画像検出の例](scenarios/examples.md)を使い、問題がある場合は[トラブルシューティング](troubleshooting.md)を参照してください。
