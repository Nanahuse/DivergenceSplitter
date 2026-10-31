# トラブルシューティング

[日本語（正本）](troubleshooting.md) | [English](troubleshooting.en.md)

[ドキュメント一覧](../README.md)

まずMonitorで映像の到着、各インスタンスのReady状態、最後のActionとエラーを確認してください。次にDiagnosticsで有効なPhase、Split、Conditionの状態とスコアを調べます。

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
| NDIランタイムを初期化できない | ZIP全体を展開し、DLLを実行ファイルの隣に置いてください。ローダーはPATHや作業ディレクトリではなくアプリのディレクトリから読みます。後述の `--ndi-check` も使えます。 |

再試行可能なカメラのopen／readエラーは取得処理が再試行します。モード、デコード、正規化、致命的なSDKエラーでは取得を停止する場合があります。Profileを修正してApplyし、最後の静止画だけでなくフレーム数の増加を確認してください。

## Bridge接続の問題

- 現在のLiveSplitレイアウトにLiveSplit Bridgeがあり、StatusがRunningであることを確認します。WebSocketポートをProfileの行と一致させてください。
- 同じPCでProtocol v4対応のBridgeを使います。アプリの接続先は `127.0.0.1` であり、リモートホストは設定できません。
- 複数のLiveSplitではBridgeごとに別のポートを設定し、各レイアウトを保存します。ポートが使用中だとBridgeを起動できない場合があります。
- 一時的な切断は自動で復旧する場合があります。プロトコルエラーやFailed状態では、表示された原因を修正してApplyし直してください。

操作結果がunknownの場合、要求がすでにLiveSplitへ届いた可能性があります。Runtimeは再同期し、同じ確定状態に対する同じ自動操作を抑止します。手動で繰り返す前にLiveSplitの状態を確認してください。再接続したことは前の操作の失敗を示すものではありません。

## 判定が成立しない・意図せず成立する

1. Monitorで正規化後の画像を確認します。ROIは元の映像ではなくCrop／Resize後の座標です。
2. Diagnosticsで有効なPhaseと0から始まるSplitの位置を確認します。`null` の区間には自動Ruleがありません。YAMLの区間数がLiveSplitより多いと評価を無効にします。ただし空の停止中Runには特例があります。
3. Ruleのエラー回数とConditionの状態を確認します。YAMLを読み込めても、ROIの範囲外やチャンネル・参照寸法の不一致は評価時に失敗します。[Detectorの制約](scenarios/detectors.md)を確認してください。
4. 最新・最大スコアと `minimum_score` を比較します。高い値ほど一致度、明るさ、指定色の割合が高いことを示します。方式共通のしきい値はないため、成立させたい画面と成立させたくない画面の両方で確認してください。
5. [Conditionの動作](scenarios/conditions.md)を確認します。edgeは基準となる前回値が必要です。`nth` はtrueの評価を数え、`once` はtrueを維持し、`hold` はfalseで計測し直し、`then` の次のステップは後の評価で始まります。
6. YAMLや画像を編集したら再適用します。ApplyとRuntimeのリセットは対応するConditionの状態と最大スコアを消します。ファイルを保存しただけでは再読込しません。

Pause／Resumeなど区間を進めないActionで、常にtrueの条件を使うと操作を繰り返す場合があります。sequenceや適切な状態付きConditionを使い、[Ruleのリセット](scenarios/yaml-reference.md#状態とリセット)も考慮してください。

## ログ

Windowsでは `%APPDATA%/DivergenceSplitter/diagnostics.log` に追記します。ローテーションしたファイルの末尾は `.1`、`.2`、`.3` です。設定とログのフォルダーは必要に応じて作成します。問題を再現する前に、SettingsでINFOまたはDEBUGを選び、SaveしてProfileを再適用してください。OFFでは記録しません。ログレベルを変えても、実装が出力しないイベントは追加されません。

主なイベントは `profile.apply`、`capture.error`、`instance.state`、`instance.ready`、`instance.action` です。Conditionの評価エラーはDiagnosticsで数えますが、Detectorの詳しい例外メッセージをログに記録する保証はありません。問題の報告にはアプリのリビジョン・ビルド、ProfileとYAML、入力種別、正規化後の寸法、判定状態・スコア、前後のログを添えてください。必要に応じて私用のパスや送信元名を除いてください。

## CLIでの確認

展開したアプリケーションのフォルダーで、環境に合わせたProfileを指定します。

```powershell
.\divergencesplitter-cli.exe --profile C:/DivergenceSplitter/profile.json --check
.\divergencesplitter-cli.exe --profile C:/DivergenceSplitter/profile.json --seconds 10
.\divergencesplitter-cli.exe --ndi-check
.\divergencesplitter-cli.exe --ndi-list
```

`--check` はProfileと全シナリオ・参照画像を読み、参照画像のResizeも行います。入力を開く処理、フレームとROIの互換性検査、Bridge接続、タイマー操作は行いません。時間を指定した実行は実際のSessionを動かし、LiveSplitを操作できます。正の `--seconds` を指定しなければCtrl+Cまで実行します。`--ndi-check` はランタイムを初期化し、`--ndi-list` は送信元の検索も行います。

CLIは `--settings C:/DivergenceSplitter/settings.json` も受け取ります。省略時はGUIの設定ファイルを自動読込せず、既定値を使います。終了コードは成功・検証完了が `0`、使用方法の誤りが `2`、捕捉した設定・起動・NDIエラーが `3`、SessionのRuntimeエラーが `4` です。Bridgeインスタンスが失敗しても時間指定実行が0で終わる場合があるため、表示されるインスタンス状態も確認してください。
