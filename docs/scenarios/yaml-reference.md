# YAMLリファレンス

[日本語（正本）](yaml-reference.md) | [English](yaml-reference.en.md)

[シナリオ作成](README.md) · [Condition](conditions.md) · [Detector](detectors.md) · [例](examples.md)

## シナリオの構造

```yaml
start_condition:
  type: elapsed
  duration: 2s
reset_condition: null
incomplete_condition: null
splits:
  - rules:
      - condition: {type: elapsed, duration: 3s}
        action: split
  - null
```

| ルート項目 | 必須 | 意味 |
| --- | --- | --- |
| `start_condition` | はい | タイマーがNot runningのときに `start` を要求するCondition。 |
| `splits` | はい | 順序付きのリスト。0番目はLiveSplitの区間0、1番目は区間1に対応します。空リストも受理します。 |
| `reset_condition` | いいえ | Running／Pausedのときに `reset` を要求するCondition。省略または `null` で無効にします。 |
| `incomplete_condition` | いいえ | 終了後に `undo` を要求するCondition。誤った最終Splitを戻す用途などに使います。省略または `null` で無効にします。 |

各区間は `null`、または `rules` だけを持つマッピングです。`rules` はRuleとsequenceの順序付きリストです。`null` は自動Ruleのない手動区間であり、自動でSkipを送りません。`rules: []` でも自動Ruleはありません。リストがLiveSplitの区間数より短ければ後続区間にはRuleがなく、長ければシナリオの評価を無効にします。空の停止中Runは一時的に許容しますが、状態が変わると区間数を再検証します。

Condition・Detectorの `type` とAction名は大文字・小文字を区別します。区間、Rule、Condition、Detector、ROI内の未知の項目は拒否します。ルートだけはアンカー定義やメタデータ用に追加キーを許容し、それ自体は動作を追加しません。任意のルート項目のタイプミスは無視される場合があります。必須項目には正しい構造が必要です。

## Ruleとsequence

Ruleは `condition` と `action` だけを持ちます。`condition` はConditionのマッピング、`action` は操作名のスカラーです。ConditionがtrueならActionを要求します。区間のRuleをリスト順に試し、最初にActionを返したRuleで評価を止めます。そのフレームでは後続Ruleを評価しません。Rule評価で例外が出るとエラーを数え、次のRuleを試します。通常のRuleは自動で一度限りになるわけではありません。

複数の操作を順に行うには、空でない通常Ruleのリストを `sequence` に指定します。sequenceの入れ子とAction配列は使えません。

```yaml
sequence:
  - condition: {type: elapsed, duration: 1s}
    action: pause
  - condition: {type: elapsed, duration: 2s}
    action: resume
  - condition: {type: elapsed, duration: 1s}
    action: split
```

このマッピングを区間の `rules` の1項目に置きます。これがRuleSequenceです。有効なRuleだけを評価し、Actionを返すと1段進みます。次のRuleは同じフレームではなく、後の評価から始まります。完了後はリセットまでActionを返しません。進行はRuleがActionを生成した時点で行い、すべての操作をBridgeが確認してから一括確定するものではありません。送信の失敗、再同期、区間変更によって、そのグループがリセットされる場合があります。

後続ステップも現在の区間で動く必要がある場合、区間を離れるSplit、Skip、Undo、Resetは最後に置いてください。同じ区間でのPause／Resumeの遷移では、通常はsequenceの位置を保ちます。複数の観測を順に確認して1つのActionを実行する場合は [`then`](conditions.md#then) を使います。`then` はConditionであり、RuleSequenceとは別です。

## Action

使用できる操作名は次の7種類です。対応するBridgeのタイマー操作を送ります。実行できるかはLiveSplitの状態によります。

| `action` | 動作 |
| --- | --- |
| `start` | 停止中のタイマーを開始します。`start_condition` の暗黙のActionでもあります。 |
| `split` | 現在の区間を完了します。最終区間の完了でRunが終了します。 |
| `skip` | 現在の区間をスキップします。 |
| `undo` | 前のSplitを取り消します。終了後は最後の区間へ戻ります。`incomplete_condition` の暗黙のActionです。 |
| `reset` | タイマーをNot runningに戻します。`reset_condition` の暗黙のActionです。 |
| `pause` | タイマーを一時停止します。 |
| `resume` | 一時停止したタイマーを再開します。 |

このスキーマにActionの引数、遅延、スクリプト、ゲーム内時間の操作はありません。待ち時間はConditionで表現します。アプリ共通のReaction timeは[Settings](../user-guide.md#settings)を参照してください。

## 評価順序

映像が届き、Bridgeとタイマーの状態を確認できているときは、次のグループを判定します。

| タイマーのPhase | 評価するグループ |
| --- | --- |
| Not running | `start_condition` だけ。 |
| Running／Paused | `reset_condition` を先に評価し、Resetが成立しなければ現在の区間のRule。 |
| Ended | `incomplete_condition` だけ。 |

Pausedでも時間条件や現在の区間のRuleを判定します。タイマーの一時停止で、時間条件の計測は止まりません。そのPhaseで対象にならないグループは判定しません。

### Actionの保留と確定待ち

Actionの送信や完了確認を待つ間は、別の通常Actionを始めません。通常ActionとResetは別々に確定を待ちます。ただしRunning／Pausedでは、通常Actionの反応待ち中や、送信したSplit／Skipの確定待ち中にも `reset_condition` を判定します。Resetが保留中は、新しいActionを始めません。

手動Resetと、通常Actionの反応待ち中に成立した自動Resetは、追加の反応時間を待たずに送信します。このとき、未送信の通常Actionは取り消します。それ以外の自動Actionには、設定されたReaction timeを使います。待機中に届いたタイマー情報に変化がなければ、反応待ちは続きます。

Bridgeが操作を受け付けた後は、対応するタイマーの状態変化を最大1秒待ちます。Pause／ResumeだけではSplit／Skipの完了確認にはならず、遅れて届いたSplitもResetの完了確認にはなりません。タイマー情報を受信しても、該当する状態変化がなければ確定待ちを続けます。

この1秒はBridgeが操作を受け付けた時点から数え、入力映像が止まっていても経過します。期限に達するとタイマーの状態を再確認し、確定しなかった操作の待機を終えて、対応するRuleグループをリセットします。次の自動Actionには、新しいフレームでの判定が必要です。この待機時間は、通信の応答待ちやConditionの `elapsed` とは別です。

Resetを拒否された場合もタイマーの状態を再確認し、下表の対象をリセットします。送信前に取り消しただけなら、すでに送信した通常Actionの確定待ちは残ります。状態を確認できなければ判定を止め、接続の回復を待ちます。画面での確認方法は[トラブルシューティング](../troubleshooting.md#操作の確定待ちとresetの失敗)、通信処理の設計は[アーキテクチャ](../development/architecture.md#bridgeとタイマー制御)を参照してください。

## 状態とリセット

Conditionの状態は、Profileのインスタンスごと、設定した箇所ごとに独立しています。同じアンカーを再利用しても、計測時間や回数は共有しません。リセットすると、そのConditionと組み合わせた各条件の状態を初期化し、表示を `not_evaluated` に戻します。型ごとの動作は[Conditionリファレンス](conditions.md)を参照してください。

次のタイミングで、Conditionの計測・回数やsequenceの進行をリセットします。

| イベント | リセット対象 |
| --- | --- |
| 新しいSession、Bridgeの初期同期、再接続 | すべてのグループ。 |
| Not runningへの遷移、LiveSplitのRunの更新または区間数の変更 | すべてのグループ。 |
| Undoを含む、Running／Pausedの別区間への移動 | 移動先の区間のRule。 |
| Endedへの遷移 | Incompleteグループ。 |
| EndedからRunning／Pausedへの復帰 | Incomplete、Reset、移動先の区間。 |
| 同じ位置でPauseとResumeを切り替え | 通常は区間のConditionとsequenceの状態を保持。 |
| 実行中にタイマー情報を再確認 | 上記のRun・Phase・位置の変化に応じてリセット。これらに変化がなければ、Conditionやsequenceの進行と操作の確定待ちを保持。 |
| 通常Actionの未送信・拒否、期限切れ後の再確認でも操作が未確定 | `start` ならStart、`undo` ならIncomplete、それ以外は現在の区間。 |
| Resetの未送信、期限切れ後の再確認でもResetが未確定 | Resetグループ。 |
| Resetの拒否後にタイマーの状態を確認できた場合 | Resetグループと、Not runningならStart、EndedならIncomplete、Running／Pausedなら現在の区間。通常ActionとResetの両方の確定待ちを解除。 |

Conditionごとのリセットは [`reset_when`](conditions.md#reset_when)、制限時間を超えたときの進行は [`then`](conditions.md#then) を参照してください。

## 時間表現

`elapsed.duration`、`hold.duration`、`then.within` は、0以上の小数に `ms` または `s` を直結した文字列です。例は `0ms`、`500ms`、`1.5s` です。`.5s` ではなく `0.5s` のように先頭の数字を書いてください。単位なしの数値、負数、符号、空白、指数表記、分、`1m30s` のような複合表記は拒否します。引用符は任意です。比較は原則 `>=` ですが、`then.within` の期限切れは窓の時間を厳密に超えた場合です。

## パス

シナリオの拡張子は `.yaml` または `.yml` です。拡張子の判定では大文字・小文字を区別しません。Profileには絶対パスを記録します。Detectorの `reference` は絶対パスか相対パスです。相対パスの基準はYAMLの保存フォルダーであり、Profileや作業フォルダーではありません。include、glob、環境変数、ホームディレクトリの展開は行いません。

Windowsでも `images/title.png`、`C:/game/title.png` のようにスラッシュを使えます。バックスラッシュを使うならYAMLの単一引用符で囲むと文字どおりに保持します。画像は元のチャンネル数・深度のまま読みます。[画像の制約](detectors.md#参照画像とチャンネル)を参照してください。

## YAMLのアンカー・エイリアス・マージ

`&name` と `*name` はrapidyaml（ryml）が扱うYAMLの標準機能です。共通定義を作り、ConditionやDetectorのマッピング全体をエイリアスで再利用できます。アンカーはルート以外でも定義できます。参照先は同じ名前で参照位置より前にある最後のアンカーです。

```yaml
bright: &bright
  type: detected
  minimum_score: 0.8
  detector: {type: mean_brightness}
start_condition: *bright
splits:
  - rules:
      - condition:
          type: falling_edge
          condition: *bright
        action: split
```

ルートの `bright` はアンカー定義を置くだけの項目です。参照した各箇所で `once` などのConditionの状態は独立しており、計測時間や回数を共有しません。

`<<: *name` で共通のマッピングを取り込み、一部の値を変更できます。入れ子のマージにも対応します。

```yaml
definitions:
  detected: &detected
    type: detected
    minimum_score: 0.9
    detector: {type: mean_brightness}

start_condition:
  <<: *detected
  minimum_score: 0.95

splits:
  - rules:
      - condition:
          <<: *detected
          minimum_score: 0.8
        action: split
```

優先順位はrapidyaml 0.16.0の標準動作に従います。単一マージで上書きする明示値は必ず `<<` **より後**に書いてください。`<<` より前の明示値はマージ元に上書きされます。`<<: [*a, *b]` では、同じキーがあれば**後ろの `b` が優先**されます。複数マージでは、`<<` の後ろに書いた明示値も後続のマージ元に上書きされる場合があります。これは、マージキーのYAML 1.1定義にある「明示値が常に優先」「リストの先頭が優先」とは異なります。

複数マージの結果を確実に上書きするには、結果をいったんアンカーにまとめてから単一マージを使います。

```yaml
a: &a {type: detected, minimum_score: 0.2}
b: &b {minimum_score: 0.8, detector: {type: mean_brightness}}
combined: &combined {<<: [*a, *b]}
start_condition:
  <<: *combined
  minimum_score: 0.95
splits: []
```

マージはマッピング単位であり、入れ子のDetectorなどを変更する場合は、そのマッピングにも `<<` を指定します。

マージキーはYAML 1.2のコア仕様ではなく、rapidyamlが対応する拡張機能として利用します。エイリアスやマージを使った箇所にも、通常と同じ必須項目・未知キー・型・値の制約が適用されます。元のYAMLにある重複キーは拒否します。存在しないアンカー、循環参照、マッピング以外を指すマージはYAMLエラーとして読み込みに失敗します。スキーマ違反はスキーマエラーとなり、いずれもアプリケーションを終了させません。
