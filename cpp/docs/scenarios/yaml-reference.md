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

有効な同期済みスナップショットがあるフレームでは、次のグループを評価します。

| タイマーのPhase | 評価するグループ |
| --- | --- |
| Not running | `start_condition` だけ。 |
| Running／Paused | `reset_condition` を先に評価し、Resetが成立しなければ現在の区間のRule。 |
| Ended | `incomplete_condition` だけ。 |

Pausedでも経過時間とSplitのRuleを評価します。タイマーの一時停止でアプリの単調増加時計は止まりません。無効なグループは呼び出しません。有効なCondition内の短絡評価については[Conditionの評価](conditions.md#評価と短絡処理)を参照してください。

Actionの確定待ち中は通常の別Actionを抑止します。Reset条件は待機中のSplit／Skipに割り込めます。現行Runtimeでは、遷移がないまま1秒の評価時刻上のタイムアウトに達すると、保留を消して対応するグループをリセットし、後のフレームで評価を再開します。Bridgeの拒否、切断、結果不明時の再試行は[アーキテクチャ](../development/architecture.md#bridgeとタイマー制御)も参照してください。

## 状態とリセット

ProfileのインスタンスごとにConditionツリーを読み込み直します。アンカーを再利用しても、使用箇所ごとに独立したオブジェクトを作るため、時計やカウンターは共有しません。Conditionのリセットは状態を `not_evaluated` に戻し、子も再帰的にリセットします。各型が消す内部状態は[Condition](conditions.md)に記載しています。

現行Runtimeは次のタイミングでリセットします。

| イベント | リセット対象 |
| --- | --- |
| 新しいSession、Bridgeの初期同期、再接続 | すべてのグループ。 |
| Not runningへの遷移、またはLiveSplitの区間数変更 | すべてのグループ。 |
| Undoを含む、Running／Pausedの別区間への移動 | 移動先の区間のRule。 |
| Endedへの遷移 | Incompleteグループ。 |
| EndedからRunning／Pausedへの復帰 | Incomplete、Reset、移動先の区間。 |
| 同じ位置でPauseとResumeを切り替え | 通常は区間のConditionとsequenceの状態を保持。 |
| 同じPhase・位置の遷移更新 | 現在の区間。操作後のQueryで状態が変わらなかった場合も該当することがあります。 |
| 状態またはRunのリビジョンが進んだ再同期 | すべてのグループ。進んでいなければグループの状態を保ち、保留Actionだけを消します。 |
| Actionの未送信、拒否、確定待ちのタイムアウト | `start` ならStart、`undo` ならIncomplete、`reset` ならReset、それ以外は現在の区間。 |

[`reset_when`](conditions.md#reset_when) はReset条件がtrueのときに自身の2つの子ツリーをリセットします。`then.within` のタイムアウトは異なり、子の状態はリセットせずステップの進行だけをやり直します。

## 時間表現

`elapsed.duration`、`hold.duration`、`then.within` は、0以上の小数に `ms` または `s` を直結した文字列です。例は `0ms`、`500ms`、`1.5s` です。`.5s` ではなく `0.5s` のように先頭の数字を書いてください。単位なしの数値、負数、符号、空白、指数表記、分、`1m30s` のような複合表記は拒否します。引用符は任意です。比較は原則 `>=` ですが、`then.within` の期限切れは窓の時間を厳密に超えた場合です。

## パス

シナリオの拡張子は `.yaml` または `.yml` です。拡張子の判定では大文字・小文字を区別しません。Profileには絶対パスを記録します。Detectorの `reference` は絶対パスか相対パスです。相対パスの基準はYAMLの保存フォルダーであり、Profileや作業フォルダーではありません。include、glob、環境変数、ホームディレクトリの展開は行いません。

Windowsでも `images/title.png`、`C:/game/title.png` のようにスラッシュを使えます。バックスラッシュを使うならYAMLの単一引用符で囲むと文字どおりに保持します。画像は元のチャンネル数・深度のまま読みます。[画像の制約](detectors.md#参照画像とチャンネル)を参照してください。

## YAMLのアンカーとエイリアス

`&name` と `*name` はyaml-cppが扱うYAMLの標準機能であり、アプリ独自の参照登録機能ではありません。ルートで共通定義を作り、ConditionやDetectorのマッピング全体をエイリアスで再利用できます。

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

ルートの `bright` はアンカー定義を置くだけの項目です。参照した各箇所で独立したRuntimeオブジェクトを作ります。アプリはマージキー `<<` を展開しません。キーを検査するマッピングでは未知の項目として拒否します。マージによる継承ではなく、マッピング全体を再利用してください。循環エイリアスを使った再帰定義には対応していません。
