# はじめに

[ドキュメント一覧](../README.md)

## 目次

- [ダウンロードと起動](#ダウンロードと起動)
- [LiveSplit.Bridgeへの接続](#livesplitbridgeへの接続)
- [入力とシナリオの設定](#入力とシナリオの設定)
- [最初の自動Splitの確認](#最初の自動splitの確認)

映像入力とLiveSplitを設定し、経過時間でStartとSplitを行うサンプルを試します。参照画像は不要です。

## ダウンロードと起動

[インストール手順](../README.md#インストール)に沿ってZIPを展開し、`DivergenceSplitter.exe` を起動します。

## LiveSplit.Bridgeへの接続

1. [LiveSplit.Bridgeの導入手順](https://github.com/Nanahuse/LiveSplit.Bridge#インストール)に沿って、Protocol v4対応版をインストールし、LiveSplitのレイアウトにLiveSplit Bridgeを追加して保存します。
2. Bridgeの設定でWebSocketポートを `54000` にし、StatusがRunningであることを確認します。DivergenceSplitterとLiveSplitは同じPCで起動してください。
3. LiveSplitに1区間のテスト用Runを作成して保存し、タイマーを停止状態にします。以降の手順で、このタイマーを実際に操作します。

## 入力とシナリオの設定

1. アプリと同じリビジョンの [minimal-scenario.yaml](../examples/minimal-scenario.yaml) をダウンロードします。
2. ProfileのInputを開き、テストに使う映像入力を選びます。
   - **Camera**では、Detect camerasを押し、機器とモードを選びます。このテストではRequest 60 fpsをオフにします。
   - **Video file**では、10秒より長いローカルの録画を選びます。たとえばMJPEG形式のAVIを使えます。
   - **NDI**では、送信元を起動してSearch againを押し、一覧から公開名を選びます。[NDI Runtime](../README.md#インストール)が必要です。
3. InputでCrop marginsとResizeをオフにします。Input PreviewのPreview inputをオンにして、映像が表示されることを確認します。プレビューを開始できない場合は[入力の下書きプレビュー](user-guide.md#入力の下書きプレビュー)を参照してください。
4. Scenarios & Connectionsを開き、Add instanceで行を追加します。Bridge portに `54000` を指定し、その行のBrowseでダウンロードしたYAMLを選びます。このテストで使わない行はRemoveで削除してください。
5. Applyを押します。映像が届き、Bridgeとの同期が済むと、シナリオの判定が始まります。

## 最初の自動Splitの確認

1. Monitorを開き、Captureにポインターを置いてフレーム数が増えていることを確認します。対象のInstanceがReadyになっていることも確認してください。
2. 開始条件を初めて判定してから約2秒後にLiveSplitがStartします。最初の区間の判定が始まってから約3秒後にSplitし、Runが終了します。確認が終わるまで映像を送り続けてください。
3. ProfileのSave Asで設定を保存します。保存と適用の違いは[Profileの操作](user-guide.md#profileの操作)を参照してください。

テストを終えたらアプリを閉じます。このサンプルは映像が届いた状態でタイマーをResetすると再びStartします。うまく動かない場合は[トラブルシューティング](troubleshooting.md)を参照してください。次に画像を使った判定を試す場合は、[画像が現れたらStartし、消えたらSplitする例](scenarios/examples.md#画像の検出)に進んでください。
