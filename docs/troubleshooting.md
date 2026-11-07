# トラブルシューティング

[日本語（正本）](troubleshooting.md) | [English](troubleshooting.en.md)

[ドキュメント一覧](../README.md)

問題が起きたら、まずMonitorで映像が届いているか、接続がReadyになっているか、最後のActionやエラーが何かを確認してください。判定がおかしい場合は、Monitorで現在のSplit位置とConditionの結果・スコアを調べます。

## 入力の問題

| 症状 | 確認と復旧 |
| --- | --- |
| カメラが見つからない、設定したカメラが未接続 | 再接続し、同じ機器を使う他のアプリを閉じます。Detect camerasでバックエンド・機器・モードを選び直してください。同名の機器は正しいインデックスが必要です。 |
| DirectShowのサブタイプを選択・確認できない | 別の選択可能なモードかMedia Foundationを選びます。GUIDを推測で記述しないでください。[カメラの制約](configuration.md#cameraキャプチャーカード)を参照してください。 |
| キャプチャーモードを拒否される | モードを再列挙し、Request 60 fpsを無効にして、利用可能なサイズ・FPSを選びApplyします。 |
| 動画を開けない・デコードできない | 絶対パスとアクセス権を確認し、そのOpenCVビルドが扱えるコーデックの録画を試します。ファイル選択画面の拡張子は再生対応の保証ではありません。 |
| 動画の末尾に達した | 末尾では停止します。ループしないため、Applyで先頭から再生し直してください。 |
| Cropの余白が収まらない | Resize前の入力寸法に合わせて余白を減らします。 |
| このビルドでNDIを使えない | 公式のNDI対応ZIPを使うか、[SDKを有効にしてビルド](development/building.md#ndi対応ビルド)してください。 |
| NDI送信元が見つからない・映像が来ない | 送信元を起動し、公開名、ネットワーク接続、ファイアウォール設定を確認してSearch againを押します。保存済みの名前はオフラインでも残ります。通常のタイムアウトは致命的なエラーではなく、送信元が戻ると受信を再開できます。 |
| NDI Runtimeを初期化できない | NDI Runtimeがインストールされているか、`NDI_RUNTIME_DIR_V6` が正しいかを確認し、アプリを再起動してください。`--ndi-check` でも状態を確認できます。 |

カメラを開く処理や読み取りで、再試行できるエラーが起きた場合は、自動でやり直します。一方、モードの不一致、デコード、画像変換、回復できないSDKエラーでは、取得を止める場合があります。Profileを修正してApplyしたら、映像が表示されるだけでなく、フレーム数も増えていることを確認してください。

## Bridge接続の問題

- 現在のLiveSplitレイアウトにLiveSplit Bridgeがあり、StatusがRunningであることを確認します。WebSocketポートをProfileの行と一致させてください。
- 同じPCでProtocol v4対応のBridgeを使います。アプリの接続先は `127.0.0.1` であり、リモートホストは設定できません。
- 複数のLiveSplitではBridgeごとに別のポートを設定し、各レイアウトを保存します。ポートが使用中だとBridgeを起動できない場合があります。
- 一時的な切断は自動で復旧する場合があります。プロトコルエラーやFailed状態では、表示された原因を修正してApplyし直してください。

操作結果がunknownの場合は、LiveSplitがすでに操作を受け取っている可能性があります。アプリはタイマーの状態を確認し直しますが、同じ状態に対して同じ自動操作を繰り返し送らないようにします。

手動で操作を繰り返す前に、LiveSplitの表示を確認してください。再接続したからといって、直前の操作が失敗したとは限りません。

## 操作の確定待ちとResetの失敗

Current evaluationにPendingやWaiting for Reset confirmationが出ている間は、アプリが操作の送信や結果の確認を待っています。Monitorの最後のActionと、LiveSplitの実際の状態・Split位置を見比べてください。

操作結果がokでも、タイマーの状態変化をまだ確認できていない場合があります。通常ActionとResetは別々に確認します。Pause／ResumeしただけではSplit／Skipを確認したことにはならず、遅れて届いたSplitもResetの確認には使いません。

Bridgeが操作を受け付けた後は、対応する状態変化を最大1秒待ちます。映像が止まっていても、この期限は進みます。期限に達したらタイマーを再確認し、それでも結果が確定しなければ待機を終えて、対応するRuleをリセットします。

その後の自動操作には、新しいフレームでの判定が必要です。映像と接続の両方が戻っているかを確認してください。反応時間やRuleとの関係は[YAMLリファレンス](scenarios/yaml-reference.md#actionの保留と確定待ち)を参照してください。

Resetが拒否されたら、表示されたエラーを確認してください。アプリは現在のタイマー状態を調べ直し、通常ActionとResetの確定待ちを終えます。そのうえで、Reset条件と、現在のタイマー状態・Split位置に対応する条件をリセットします。タイマーの状態を確認できなければ、判定を止めて接続を回復します。

ConnectingやFailedが続くときは、BridgeのStatus、ポート、ログを調べてください。Reset Allを使った場合も、すべての行で成功したかを確認します。

## 判定が成立しない・意図せず成立する

1. Monitorで正規化後の画像を確認します。ROIは元の映像ではなくCrop／Resize後の座標です。
2. Monitorで有効なPhaseと0から始まるSplitの位置を確認します。`null` の区間には自動Ruleがありません。YAMLの区間数がLiveSplitより多いと評価を無効にします。ただし空の停止中Runには特例があります。
3. Ruleのエラー回数とConditionの状態を確認します。YAMLを読み込めても、ROIの範囲外やチャンネル・参照寸法の不一致は評価時に失敗します。[Detectorの制約](scenarios/detectors.md)を確認してください。
4. 最新・最大スコアと `minimum_score` を比較します。高い値ほど一致度、明るさ、指定色の割合が高いことを示します。方式共通のしきい値はないため、成立させたい画面と成立させたくない画面の両方で確認してください。
5. [Conditionの動作](scenarios/conditions.md)を確認します。edgeは基準となる前回値が必要です。`nth` はtrueの評価を数え、`once` はtrueを維持し、`hold` はfalseで計測し直し、`then` の次のステップは後の評価で始まります。
6. YAMLや画像を編集したら再適用します。ApplyとRuntimeのリセットは対応するConditionの状態と最大スコアを消します。ファイルを保存しただけでは再読込しません。

Pause／Resumeのように区間を移動しない操作では、条件がtrueのままだと同じ操作を繰り返す場合があります。sequenceで操作を順番に並べるか、条件が変化したときだけ成立するConditionなどを使ってください。条件がいつやり直しになるかは、[Ruleのリセット](scenarios/yaml-reference.md#状態とリセット)を参照してください。

## ログ

ログは `%APPDATA%/DivergenceSplitter/diagnostics.log` に追記します。古いログを退避したファイルには、末尾に `.1`、`.2`、`.3` が付きます。保存先のフォルダーは必要に応じて作成します。

問題を再現する前に、SettingsのLog levelをINFOまたはDEBUGにしてSaveし、Profileを再びApplyしてください。OFFでは記録しません。DEBUGを選んでも、もともと記録対象でないイベントは追加されません。

主なログ項目は `profile.apply`、`capture.error`、`instance.state`、`instance.ready`、`instance.action` です。Conditionの判定エラーはMonitorで数えますが、Detectorの詳しい例外メッセージがログに残るとは限りません。

問題を報告するときは、アプリのリビジョン・ビルド、ProfileとYAML、入力の種類、Crop／Resize後の寸法、判定結果・スコア、問題が起きた前後のログを添えてください。必要に応じて、個人的なファイルパスや送信元の名前を取り除いてください。

## CLIでの確認

展開したアプリケーションのフォルダーで、環境に合わせたProfileを指定します。

```powershell
.\divergencesplitter-cli.exe --profile C:/DivergenceSplitter/profile.json --check
.\divergencesplitter-cli.exe --profile C:/DivergenceSplitter/profile.json --seconds 10
.\divergencesplitter-cli.exe --ndi-check
.\divergencesplitter-cli.exe --ndi-list
```

`--check` は、Profile、各シナリオ、参照画像を読み込んで設定を検証します。設定されていれば参照画像のResizeも行います。映像入力は開かず、Bridgeにも接続しないため、タイマー操作は送りません。実際の映像とROIが合うかどうかは、この方法では確認できません。

`--seconds` を指定した実行では実際に映像を取得してシナリオを動かし、LiveSplitを操作します。正の秒数を指定しなければ、Ctrl+Cを押すまで続きます。`--ndi-check` はNDIランタイムの初期化を確認し、`--ndi-list` は送信元の検索も行います。

CLIの設定ファイルは `--settings C:/DivergenceSplitter/settings.json` で指定します。省略した場合は既定値を使い、GUIの設定ファイルを自動では読み込みません。

終了コードは、成功または検証完了が `0`、引数の誤りが `2`、設定・起動・NDIで捕捉したエラーが `3`、実行中のSessionのエラーが `4` です。時間を指定した実行では、個々のBridge接続が失敗しても `0` で終了する場合があります。終了コードだけでなく、表示された各インスタンスの状態も確認してください。
