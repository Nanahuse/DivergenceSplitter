# 利用ガイド

[日本語（正本）](user-guide.md) | [English](user-guide.en.md)

[ドキュメント一覧](../README.md) · [初回の手順](getting-started.md)

## Monitor

Monitorには、全シナリオが使うCrop／Resize後の入力画像を表示します。入力欄には公開したフレーム数、計測した取得FPS、取得が動作中かを表示します。表には各シナリオの接続状態、タイマーのPhase、Splitの位置、最後のAction、エラーまたは操作結果を表示します。シナリオとSplitのインデックスは0から始まります。

Processing FPSはインスタンスごとの評価回数から求めた処理速度です。入力FPSとは異なり、同じ入力でもインスタンスごとに値が変わる場合があります。Current evaluationには現在のConditionの説明・状態と、評価したDetectorのしきい値・最新スコアの概要を表示します。概要にポインターを置くと追加の行を確認できます。完全なConditionツリーと最大スコアはDiagnosticsで確認してください。PendingやWaiting for Reset confirmationの意味は[操作の確定待ち](troubleshooting.md#操作の確定待ちとresetの失敗)を参照してください。

ReadyはBridgeとの同期が済んだ状態です。入力とDiagnosticsも確認してください。Readyでも条件の成立や区間数の整合性を示すわけではありません。切断中のインスタンスはActionを評価できません。他のインスタンスの接続は独立しています。

### Reset All

Reset Allを2秒間押し続けます。途中で離すか、ポインターをボタンの外へ動かすとキャンセルします。押し続けると各インスタンスに手動Resetを要求します。各インスタンスが要求を処理できるとき、Running、Paused、EndedのタイマーにResetを送ります。停止中のタイマーには不要です。複数のLiveSplitに対して一括で成功する操作ではないため、インスタンスごとの結果を確認してください。

Reset Allはタイマーをリセットする操作です。下書きやProfileファイルを削除しません。リセット後に開始条件が成立すると、Runが再び始まることがあります。

## Profileの下書き・適用済み設定・ファイル

Profileでは入力1つ、任意の画像変換、Bridgeポートとシナリオパスの一覧を設定します。Add instance、Remove instance、Browse scenario...で行を編集します。入力の設定項目とJSONの仕様は[設定リファレンス](configuration.md)にまとめています。

| 操作 | 動作 |
| --- | --- |
| 項目を編集 | 下書きだけを変更します。実行中のRuntimeは適用済みの値を使い続けます。 |
| Apply | シナリオ・参照画像の読み込みと入力の選択を検証し、下書きでSessionを置き換えます。映像取得とインスタンスの状態を初期化し、動画は先頭から開き直します。Profile JSONは保存しません。 |
| Revert draft | 適用済みのProfileで下書きを置き換えます。ファイルを読み直したり、送信済みのタイマー操作を取り消したりはしません。 |
| File > Open Profile... | JSONを読み込んですぐに適用し、下書きも置き換えます。 |
| File > Save Profile As... | 現在の下書きをJSONに書き、パスを記憶します。下書きの適用や完全な検証は行いません。 |

Applyの前に保存すると、未適用または無効な設定を保存する場合があります。編集、下書きプレビューでの確認、Apply、Monitorでの確認、保存の順で進めてください。映像入力を開く処理は非同期なので、Applyの成功後に入力エラーが出る場合があります。Monitorでエラーを確認し、修正して再びApplyしてください。

YAMLや画像の変更は自動監視しません。編集後はProfileを再適用するか開き直してください。最後に開いた、または保存したProfileのパスを記憶します。次回の起動時にそのファイルが存在すれば、読み込みと適用を試みます。

### 入力の下書きプレビュー

ProfileのDraft input previewでPreview inputを有効にすると、Sessionが停止している間にCamera／Video／NDIの下書き入力を確認できます。開けた入力の寸法、バックエンドの報告FPS（取得できる場合）、実測の受信FPS、変換後の出力寸法を表示します。Crop／Resizeの変更は同じ入力を開き直さずに反映し、送信元が一時停止していても最後の画像で変換を確認できます。

プレビューは入力と画像変換の確認用です。シナリオの評価やBridge操作は行いません。Resize reference imagesによる参照画像の変換もここでは確認できないため、Apply後にDiagnosticsで判定を確認してください。

Sessionの実行中は下書きプレビュー用の入力を開きません。Stop Session and preview draftを押すとSessionを停止して編集内容を確認でき、Applyでシナリオの実行を再開できます。Profileから離れる、Preview inputをオフにする、Sessionを開始する操作でプレビューの入力を解放します。動画はプレビューでも再生し、Applyでは先頭から開き直します。プレビューにエラーが出たら入力を修正するかPreview inputを切り替えて再試行してください。

## Diagnostics

シナリオのツリーを展開するとRun、Start、Reset、Incomplete、各Splitを確認できます。RuleにはAction、sequenceには現在のステップを表示します。Conditionには状態を表示し、`detected` には最新スコア、リセット後の最大スコア、しきい値も表示します。評価回数、直近の評価時間（ミリ秒）、Ruleのエラー回数も確認できます。

| 状態 | 意味 |
| --- | --- |
| `not_evaluated` | 読み込み直後またはリセット後で、まだ評価していません。 |
| `true`／`false` | 直近の通常評価の結果です。 |
| `skipped` | その位置では結果を使っていません。短絡評価中も状態を更新するConditionがあります。[Condition](scenarios/conditions.md)を参照してください。 |
| `error` | 参照画像の形状不一致など、評価中に例外が発生しました。 |

有効なRuleグループだけを評価します。無効なグループには以前の状態が残るため、表示スコアが最新フレームの値とは限りません。Phaseごとの選択とリセットは[YAMLリファレンス](scenarios/yaml-reference.md)で説明します。

## Settings

- Log level：`OFF`、`DEBUG`、`INFO`、`WARNING`、`ERROR`から選びます。既定値は `INFO` です。既存のログイベントを絞り込む設定であり、DEBUGでも全フレームのDetectorスコアは記録しません。
- Reaction time：0以上のミリ秒値です。既定値は `0`、画面上の上限は `5000` です。自動Actionは通常、判定の原因となったフレームの取得時刻にこの時間を足した時刻まで待ちます。処理に使った時間も待ち時間に含みます。Resetの割り込みと遅延の例外は[Actionの保留と確定待ち](scenarios/yaml-reference.md#actionの保留と確定待ち)を参照してください。判定のしきい値や、正確なタイマー操作時刻の保証ではありません。
- Theme：LightまたはDarkを選びます。保存すると表示に反映します。

Saveで設定を保存します。ReloadはControllerが持つ保存済みの値をSettingsの項目に戻します。Reaction timeとログレベルをRuntimeに反映するにはProfileを再適用してください。設定はProfileと別に `%APPDATA%/DivergenceSplitter/settings.json` に保存します。全項目は[設定リファレンス](configuration.md#アプリケーション設定)を参照してください。

## AboutとCLI

Aboutにはアプリのバージョンとプロジェクト・ライセンスへのリンクを表示します。画面を使わない設定の検証と実行は[CLIでの確認](troubleshooting.md#cliでの確認)を参照してください。
