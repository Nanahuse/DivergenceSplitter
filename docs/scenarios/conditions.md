# Conditionリファレンス

[日本語（正本）](conditions.md) | [English](conditions.en.md)

[シナリオ作成](README.md) · [YAMLのリセット](yaml-reference.md#状態とリセット)

Conditionは必須の `type` を持つマッピングです。次の12種類が公開設定のすべてです。任意と明記した項目以外は必須です。`condition` は子1つのマッピング、`conditions` は子の順序付きリストです。未知の項目は拒否します。

## 評価と短絡処理

`all` と `any` はYAMLの順に子を処理します。結果が決まった後も、残りの子を短絡モードで呼び出します。無効なRuleグループを呼ばない場合とは異なります。

| 短絡モードで呼ばれる型 | 状態の更新 |
| --- | --- |
| `detected` | Detectorを実行せず、最新・最大スコアも更新しません。 |
| `all`、`any`、`not` | 子へ短絡モードを渡します。 |
| `rising_edge`、`falling_edge`、`once`、`hold`、`nth` | 自身の結果が使われなくても、子を通常評価して内部状態を更新します。完了済みの `once` と `nth` は子をskippedにするだけです。 |
| `elapsed` | 時計の開始・進行と完了状態を更新します。 |
| `reset_when` | Reset条件を通常評価し、必要ならリセットした後、主条件を短絡評価します。 |
| `then` | 現在の子だけを通常評価して進行・完了を更新します。他の子は評価せずskippedにします。 |

ノード自身は `skipped` と表示されても、子は通常評価の結果を表示する場合があります。短絡中の `nth` は指定回数に達しても親へtrueを返さず、edgeも遷移を記録しても親へtrueを返さない場合があります。状態付きConditionの配置に注意してください。先行する `all` の子がfalseでも、後ろの時計やカウンターは停止するとは限りません。

一方、`then` の無効なステップや完了済みのラッパーが使う `mark_skipped` は、子を実行せず診断状態だけを再帰的に変更します。最初のActionより後のRuleや、無効なPhase・区間のグループは評価しません。

時間の比較にはフレームごとに取得したアプリの単調増加時刻を使います。LiveSplitの時間やフレーム数ではありません。評価がなければ結果も変わりません。タイマーのPauseや映像の途切れで時計は止まらず、次の評価で時間条件が成立する場合があります。`hold` がfalseを観測できるのは評価したフレームだけです。

## detected

```yaml
type: detected
minimum_score: 0.9
detector: {type: mean_brightness}
```

`minimum_score`（有限数）と `detector`（Detectorのマッピング）が必須です。`score >= minimum_score` でtrueになり、等しい場合も成立します。しきい値を `[0, 1]` に制限する検証はありませんが、全Detectorの出力範囲は `[0, 1]` です。1より大きい値では成立せず、0なら有効な全スコアで成立します。

リセット後の最新・最大スコアを保持します。リセットすると両方を消し、短絡中は更新しません。Detectorの例外はfalseではなく `error` となり、RuntimeはRuleエラーとして数えます。

## all

```yaml
type: all
conditions:
  - {type: elapsed, duration: 1s}
  - {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

`conditions` が必須です。すべての子がtrueならtrueです。左から評価し、最初のfalse以降は短絡モードにします。空リストはtrueです。独自の内部状態はなく、リセットで全子を再帰的にリセットします。

## any

```yaml
type: any
conditions:
  - {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
  - {type: elapsed, duration: 10s}
```

`conditions` が必須です。どれかの子がtrueならtrueです。最初のtrue以降は短絡モードにします。空リストはfalseです。独自の内部状態はなく、リセットで全子を再帰的にリセットします。

## not

```yaml
type: not
condition: {type: detected, minimum_score: 0.1, detector: {type: mean_brightness}}
```

`condition` が必須です。子の通常評価の結果を反転します。短絡モードでは子にもそのモードを渡します。独自の内部状態はなく、リセットで子をリセットします。

## rising_edgeとfalling_edge

```yaml
type: rising_edge
condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

どちらも `condition` が必須です。`rising_edge` はfalseからtrue、`falling_edge` はtrueからfalseへの変化でtrueになります。初回は基準値を記録するだけでfalseです。初回の子がすでにtrueでもrising edgeにはならず、すでにfalseでもfalling edgeにはなりません。

以降は短絡モードを含めて子の現在値を記録します。結果は1回の評価だけtrueになるパルスであり、trueを維持しません。リセットでは前回値を消して子もリセットします。falling側は同じ項目で `type: falling_edge` と指定します。

## once

```yaml
type: once
condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

`condition` が必須です。子が初めてtrueになると完了を記録し、リセットまで毎回trueを返します。1フレームだけのパルスではありません。完了後は子をskippedにし、子の状態を更新しません。短絡中にも完了する場合があります。リセットでは完了状態を消し、子もリセットします。

## elapsed

```yaml
type: elapsed
duration: 3s
```

`duration` が必須です。[時間表現](yaml-reference.md#時間表現)に従って指定します。リセット後の最初の評価から計測し、短絡モードでの初回呼び出しも開始に含みます。ファイルの読み込み、Apply、タイマー開始、区間への移動が、それだけでこの時計の開始になるわけではありません。その時点でこのノードが初めて評価される場合に限り一致します。

経過がduration以上になるとtrueとなり、リセットまで維持します。`0s` は初回でtrueです。リセットでは開始時刻、完了状態、経過時間の表示値を消します。

## hold

```yaml
type: hold
duration: 500ms
condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

`duration` と `condition` が必須です。子の最初のtrueで計測を始め、以降に観測した値が連続してtrueのままduration以上続くとtrueです。falseを1回でも観測すると開始時刻を消してfalseを返し、次のtrueで新しい計測を始めます。

完了は固定しません。成立後も子がfalseならfalseに戻ります。`0ms` は子の結果に即座に従います。短絡中も更新します。リセットでは計測・経過時間の表示値を消し、子もリセットします。

## nth

```yaml
type: nth
count: 3
condition:
  type: rising_edge
  condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

`count`（1以上の整数）と `condition` が必須です。子がtrueになった評価を毎回数えます。連続したtrueフレームや短絡中の呼び出しも含み、falseでは回数を消しません。count回目だけtrueを返し、その後はリセットまでfalseを返して子をskippedにします。

フレーム数ではなく出現回数を数えるには、例のように検出を `rising_edge` で包みます。リセットでは回数と完了状態を消し、子もリセットします。

## reset_when

```yaml
type: reset_when
condition:
  type: once
  condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
reset_condition:
  type: not
  condition: {type: detected, minimum_score: 0.1, detector: {type: mean_brightness}}
```

`condition` と `reset_condition` が必須です。毎回Reset条件を先に通常評価します。trueならReset条件自身を含む両方の子をリセットし、その同じフレームで主条件を評価して結果を返します。リセットによってfalseを強制したり、1フレーム待ったりはしません。

短絡モードでもReset条件は通常評価し、主条件だけを短絡評価します。外部からのリセットも両方の子をリセットします。独自の追加状態はありません。

## then

```yaml
type: then
within: 5s
conditions:
  - {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
  - {type: elapsed, duration: 1s}
```

空でない `conditions` が必須です。`within` は任意の時間で、省略時は期限がありません。有効なステップだけを評価し、trueなら1段だけ進みます。次のステップは後のフレームから評価します。前後のステップは実行せずskippedにします。falseなら同じステップで待ちます。1要素ならその子の最初のtrueで完了します。

複数ステップの場合、`within` はステップ0の成立時に始まります。後続全体の制限時間であり、各ステップ別の制限ではありません。後の評価の前に経過が窓を厳密に超えるとステップ0へ戻り、同じフレームで再び評価できます。等しい時刻は期限内です。

期限切れで消すのは位置と窓の開始時刻だけです。子の状態は消さないため、以前の `elapsed`、`once`、`nth` の状態が次の試行に影響する場合があります。

最後のステップが成立するとtrueになり、リセットまで維持します。短絡モードでも進行・完了します。完全なリセットでは位置、窓の開始時刻、完了状態を消し、すべての子の状態もリセットします。例の1秒の時計はステップ0の成立時ではなく、ステップ1を初めて評価したときに始まります。

`then` は複数の観測を1つのConditionにまとめ、Actionを1つ実行します。[RuleSequence](yaml-reference.md#ruleとsequence) はRuleごとにActionを出して順に進む機能です。
