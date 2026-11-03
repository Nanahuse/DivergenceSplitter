# Conditionリファレンス

[日本語（正本）](conditions.md) | [English](conditions.en.md)

[シナリオ作成](README.md) · [YAMLのリセット](yaml-reference.md#状態とリセット)

Conditionは必須の `type` を持つマッピングです。次の12種類が公開設定のすべてです。任意と明記した項目以外は必須です。`condition` は子1つのマッピング、`conditions` は子の順序付きリストです。未知の項目は拒否します。

## 時間・回数・状態の扱い

時間条件は映像を判定した時点のアプリの経過時間を使います。LiveSplitの実時間・ゲーム内時間やフレーム数ではありません。タイマーをPauseしたり映像が途切れたりしても計測時間は進み、次のフレームの判定で時間条件が成立する場合があります。フレームを判定するまでは、結果は更新されません。`hold` も判定したフレームで条件が続いているかを確認します。

複数のConditionを組み合わせても、他のConditionがfalseの間に時間計測や回数の記録が進む場合があります。`nth` の指定回数への到達やedgeの変化が他の条件の成立と重ならなければ、組み合わせ全体は成立しないことがあります。条件を順番に確認したい場合は [`then`](#then) を使ってください。

## detected

```yaml
type: detected
minimum_score: 0.9
detector: {type: mean_brightness}
```

`minimum_score` は有限数、`detector` はDetectorのマッピングで、どちらも必須です。スコアが `minimum_score` 以上ならtrueになり、等しい場合も成立します。しきい値自体に範囲の制限はありませんが、全Detectorのスコアは `[0, 1]` です。1より大きい値では成立せず、0なら有効な全スコアで成立します。

Diagnosticsでは最新スコアと、リセット後の最大スコアを確認できます。リセットすると両方を消します。Detectorの判定に失敗すると `error` になり、Ruleのエラー回数が増えます。falseとは区別してください。

## all

```yaml
type: all
conditions:
  - {type: elapsed, duration: 1s}
  - {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

`conditions` が必須です。指定した条件がすべて成立するとtrueになります。空リストもtrueです。リセットすると、指定したすべての条件の状態を初期化します。

## any

```yaml
type: any
conditions:
  - {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
  - {type: elapsed, duration: 10s}
```

`conditions` が必須です。指定した条件のうち、1つでも成立するとtrueになります。空リストはfalseです。リセットすると、指定したすべての条件の状態を初期化します。

## not

```yaml
type: not
condition: {type: detected, minimum_score: 0.1, detector: {type: mean_brightness}}
```

`condition` が必須です。指定した条件がfalseならtrue、trueならfalseになります。リセットすると、その条件の状態も初期化します。

## rising_edgeとfalling_edge

```yaml
type: rising_edge
condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

どちらも `condition` が必須です。`rising_edge` はfalseからtrue、`falling_edge` はtrueからfalseに変わったときに成立します。読み込み後やリセット後の初回判定は、変化を比べるための基準となるためfalseです。初回の値がすでにtrueでも `rising_edge` は成立せず、すでにfalseでも `falling_edge` は成立しません。

変化を確認した1回の判定だけtrueになり、その値を維持しません。リセットすると、それまでの変化の記録と指定した条件の状態を初期化します。`falling_edge` を使う場合は、同じ項目で `type: falling_edge` と指定します。

## once

```yaml
type: once
condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

`condition` が必須です。指定した条件が初めてtrueになると、それ以降はリセットまでtrueを維持します。1フレームだけ成立させる条件ではありません。一度成立した後は、指定した条件の値が変わっても結果は変わりません。

リセットすると成立の記録を消し、指定した条件の状態も初期化します。

## elapsed

```yaml
type: elapsed
duration: 3s
```

`duration` が必須です。[時間表現](yaml-reference.md#時間表現)に従って指定します。読み込み後やリセット後に、この条件を初めて判定した時点から計測します。ファイルの読み込み、Apply、タイマー開始、区間への移動そのものを起点にはしません。それらの操作時に初回の判定も行われる場合は、計測開始と一致します。

経過時間が `duration` 以上になるとtrueとなり、リセットまで維持します。`0s` は初回の判定でtrueです。リセットすると計測をやり直し、経過時間の表示も消します。

## hold

```yaml
type: hold
duration: 500ms
condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

`duration` と `condition` が必須です。指定した条件が初めてtrueになった時点から計測します。その後に判定した値が連続してtrueのまま `duration` 以上続くと成立します。falseを1回でも確認すると計測をやり直し、次のtrueから新しい計測を始めます。

成立後も、指定した条件がfalseになればfalseに戻ります。`0ms` はその条件の結果に従います。リセットすると計測と経過時間の表示を消し、指定した条件の状態も初期化します。

## nth

```yaml
type: nth
count: 3
condition:
  type: rising_edge
  condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

`count` は1以上の整数、`condition` はConditionのマッピングで、どちらも必須です。指定した条件がtrueになった判定を毎回数えます。連続するtrueのフレームも1回ずつ数え、falseになっても回数は消しません。`count` 回目だけtrueになり、その後はリセットまでfalseです。

画像が現れた回数を数えたい場合は、例のように `rising_edge` を組み合わせます。リセットすると回数と成立の記録を消し、指定した条件の状態も初期化します。

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

`condition` と `reset_condition` が必須です。`reset_condition` が成立したフレームで、両方の条件を初期化してから `condition` を判定します。そのため、リセットした同じフレームでも `condition` が成立すればtrueになります。リセットだけを理由にfalseにしたり、次のフレームまで待ったりはしません。

このConditionをリセットした場合は、指定した両方の条件も初期化します。

## then

```yaml
type: then
within: 5s
conditions:
  - {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
  - {type: elapsed, duration: 1s}
```

空でない `conditions` が必須です。リストの各条件を、記述した順番に成立させます。現在のステップがtrueになると1段進み、次のステップの判定は後のフレームから始まります。falseなら同じステップで待ちます。条件が1つなら、その条件の最初のtrueで完了します。

`within` は任意の制限時間です。省略すると期限はありません。複数ステップでは、最初のステップが成立した時点から、残りすべてのステップを完了するまでの時間を指定します。ステップごとの制限時間ではありません。経過時間が `within` を超えた次の判定では、最初のステップからやり直します。そのフレームで最初の条件が成立すれば再び進みます。ちょうど同じ時間なら期限内です。

期限切れでは順番だけを最初に戻し、各条件の状態はリセットしません。そのため、それまでの `elapsed` の計測、`once` の成立、`nth` の回数が次の試行に影響する場合があります。

最後のステップが成立するとtrueになり、リセットまで維持します。リセットするとステップの進行、制限時間の計測、完了の記録を消し、各条件の状態も初期化します。例の1秒の計測は2つ目の条件である `elapsed` の判定を始めた時点からです。

`then` は複数の条件を順に確認して1つのActionを実行します。各ステップで別のActionを実行したい場合は [RuleSequence](yaml-reference.md#ruleとsequence) を使ってください。
