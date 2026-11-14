# トラブルシューティング

[ドキュメント一覧](../README.md)

## 目次

- [入力の問題](#入力の問題)
  - [カメラ・キャプチャーカード](#カメラキャプチャーカード)
  - [動画ファイル](#動画ファイル)
  - [NDI](#ndi)
- [Bridge接続の問題](#bridge接続の問題)
- [操作の確定待ちとResetの失敗](#操作の確定待ちとresetの失敗)
- [判定が成立しない・意図せず成立する](#判定が成立しない意図せず成立する)
- [ログ](#ログ)

Monitorを開き、Captureにポインターを置いてフレーム数が増えているか確認します。映像が届いていれば、対象のインスタンスがReadyか、現在の区間と最後の操作結果がLiveSplitの表示と合っているかを確認してください。

## 入力の問題

Profileで入力を修正してApplyしたら、Monitorで映像が表示され、フレーム数が増えることを確認します。Cropのエラーが出る場合は、Resize前の入力寸法に合わせて余白を減らしてください。

### カメラ・キャプチャーカード

| 症状 | 確認と対処 |
| --- | --- |
| カメラが一覧に出ない | 接続を確認し、同じ機器を使っているアプリを閉じます。Detect camerasを押し、バックエンド、機器、モードを選び直します。同名の機器がある場合は番号も確認してください。 |
| モードが拒否される、寸法やFPSが合わない | Detect camerasで一覧を取り直し、Request 60 fpsをオフにして、一覧からモードを選び直します。 |
| DirectShowのサブタイプを選べない、または確認できない | 別のモードかMedia Foundationを選びます。[カメラの制約](configuration.md#cameraキャプチャーカード)を参照してください。 |

### 動画ファイル

| 症状 | 確認と対処 |
| --- | --- |
| 動画を開けない、デコードできない | ファイルの絶対パスとアクセス権を確認します。拡張子が同じでも、コーデックによって再生できない場合があります。たとえばMJPEG形式のAVIで再生を試してください。 |
| 動画の末尾で映像が止まる | 末尾に達すると取得を止めます。Applyで先頭から再生し直せます。 |

### NDI

| 症状 | 確認と対処 |
| --- | --- |
| NDI Runtimeが見つからない、または初期化できない | ProfileのNDI入力設定に表示される状態を確認します。[NDI Runtime](https://ndi.video/)のインストールと、設定している場合は `NDI_RUNTIME_DIR_V6` の場所を確認して、アプリを再起動してください。 |
| 送信元が見つからない、または映像が来ない | 送信元が動作しているか、公開名が正しいか、ネットワークとファイアウォールの設定を確認します。Search againを押して選び直してください。同じ名前の送信元が一時停止から戻ると、受信を再開できます。 |

## Bridge接続の問題

1. LiveSplitとDivergenceSplitterが同じPCで動作していることを確認します。Protocol v4に対応したLiveSplit.Bridgeを使ってください。接続先は `127.0.0.1` 固定です。
2. 現在のLiveSplitレイアウトにLiveSplit Bridgeが追加され、StatusがRunningになっているか確認します。BridgeのWebSocketポートとProfileのBridge portを合わせます。
3. 複数のLiveSplitを操作する場合は、Bridgeごとに別のポートを使い、レイアウトを保存します。StatusがRunningにならない場合は、ポートがすでに使われていないか確認してください。
4. ConnectingやFailedが続く場合は、Monitorと[ログ](#ログ)でエラーを確認し、原因を修正してApplyし直します。

## 操作の確定待ちとResetの失敗

| 表示・症状 | 確認と対処 |
| --- | --- |
| Pending、Waiting for Reset confirmation | アプリは操作の送信か結果の確認を待っています。Monitorの最後の操作結果と、LiveSplitの状態・Split位置を見比べます。 |
| 結果が `ok` のまま確定しない | Bridgeが操作を受け付けたあと、アプリは対応するタイマーの変化を最大1秒待ちます。映像が止まっていても期限は進みます。再確認しても結果が確定しない場合は、対応するRuleをリセットします。次の判定に向けて、映像と接続の両方を確認してください。 |
| 結果が `unknown` | LiveSplitが操作を受け取っている可能性があります。手動で操作し直す前に、LiveSplitの表示を確認してください。 |
| Resetが拒否される、Reset Allの一部が失敗する | インスタンスごとに操作結果とLiveSplitの状態を確認します。タイマーの状態を再確認できず接続が戻らない場合は、[Bridge接続の問題](#bridge接続の問題)を参照してください。 |

操作を送るタイミングは[YAMLリファレンス](scenarios/yaml-reference.md#操作を送るタイミング)を参照してください。失敗時にリセットされる条件も[一覧](scenarios/yaml-reference.md#状態とリセット)で確認できます。

## 判定が成立しない・意図せず成立する

1. MonitorのPreviewで、Crop／Resize後の映像を確認します。[ROI](scenarios/detectors.md#共通設定とroi)の座標は、この画像の左上が基準です。
2. Detailsでタイマーの状態と現在の区間を確認します。`null` の区間は手動です。Scenario / split count mismatchが表示されたら、[シナリオの区間数](scenarios/yaml-reference.md#シナリオの構造)をLiveSplitのRunと照合してください。
3. Ruleのエラー回数とConditionの状態を確認します。Applyで読み込めた場合でも、ROIが映像からはみ出したり、参照画像の寸法やチャンネル数が合わなかったりすると判定に失敗します。[参照画像の制約](scenarios/detectors.md#参照画像とチャンネル)を確認してください。
4. 検出したい場面と誤検出しやすい場面でスコアを見比べ、`minimum_score` を調整します。時間や回数が想定と異なる場合は、[Conditionの動作](scenarios/conditions.md)を確認してください。
5. YAMLや参照画像を修正して保存したら、Profileで再びApplyします。

PauseやResumeが意図せず繰り返される場合は、[区間内のRuleの評価順序](scenarios/yaml-reference.md#区間内のruleの評価順序)を参照してください。

## ログ

ログは `%APPDATA%/DivergenceSplitter/diagnostics.log` に追記されます。古いログには末尾に `.1`、`.2`、`.3` が付きます。

問題を再現する前に、SettingsのLog levelを `INFO` または `DEBUG` にしてSettingsのApplyを押し、Profileで再びApplyします。`OFF` では記録されません。入力エラーは `capture.error`、接続は `instance.state` と `instance.ready`、操作結果は `instance.action` を探してください。Detectorの詳しいエラーがログに出ない場合は、Monitorで判定エラーを確認します。

問題を報告するときは、アプリのリビジョンとビルド、ProfileとYAML、入力の種類、Crop／Resize後の寸法、判定結果・スコア、問題が起きた前後のログを添えてください。必要に応じて、個人のファイルパスや送信元の名前を削除してください。
