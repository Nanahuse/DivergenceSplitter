# Conditionリファレンス

[シナリオ作成](README.md) · [YAMLのリセット](yaml-reference.md#状態とリセット)

## 目次

### 共通仕様

- [条件IDと上書きできる設定](#条件idと上書きできる設定)
- [時間・回数・状態の扱い](#時間回数状態の扱い)

### Condition一覧

- [detected](#detected) — 画像のスコアがしきい値以上か判定する
- [all](#all) — すべての条件を満たしたときに成立する
- [any](#any) — いずれかの条件を満たしたときに成立する
- [not](#not) — 条件の成立・不成立を反転する
- [rising_edge](#rising_edge) — 条件が不成立から成立に変わったときに成立する
- [falling_edge](#falling_edge) — 条件が成立から不成立に変わったときに成立する
- [once](#once) — 一度成立した条件をリセットまで保持する
- [elapsed](#elapsed) — 指定時間の経過を判定する
- [hold](#hold) — 条件が一定時間続いたか判定する
- [nth](#nth) — 条件が指定回数成立したか判定する
- [reset_when](#reset_when) — 別の条件が成立したときに判定状態をリセットする
- [then](#then) — 複数の条件を指定した順番で判定する

Conditionはタイマーを操作する条件です。新しく定義するには、`type` に一覧の12種類のいずれかを指定し、その種類に応じた設定を書きます。未定義の項目があると読み込みに失敗します。

既存の定義を [`extends`](yaml-reference.md#conditionの継承) で継承する場合は、継承元の `type` を使います。継承先では `extends` で参照先を指定し、設定を変更する場合は `overrides` を使います。

`condition` には1つのConditionを、`conditions` にはConditionのリストを記述します。

## 条件IDと上書きできる設定

どのConditionでも `id` は任意です。上書き対象のルートや子条件にIDを付け、`overrides` のキーとして使います。時間や回数などの実行時の状態は使用箇所ごとに独立しています。

- `duration`、`count`、`minimum_score`、`within` など、そのConditionが持つ設定を変更できます。
- Detectorでは `reference`、`roi`、`hash_size`、色範囲など、そのDetectorが持つ設定を変更できます。
- Conditionの `type` と `id`、Detectorの `type`、子条件を指定する `conditions`、`condition`、`reset_condition` は固定です。子条件の設定を変更するには、その子のIDを直接指定します。

継承構文と `null` の扱いは[YAMLリファレンス](yaml-reference.md#conditionの継承)を参照してください。

## 時間・回数・状態の扱い

時間はアプリ側の時計で測ります。LiveSplitをPauseしたり、映像が途切れたりしても、計測中の時間は進みます。条件の結果を更新するのは、映像のフレームを判定したときです。`hold` が条件の継続を確認できるのも、判定したフレームに限られます。

複数の条件を組み合わせても、他の条件がfalseの間に時間の計測や回数の記録が進む場合があります。`all` に `nth`、`rising_edge`、`falling_edge` を含める場合は、その条件が成立した判定で他の条件も成立している必要があります。後から他の条件が成立しても、すでに過ぎた回数や変化を使い直すことはできません。

条件を順番に確認したい場合は、[`then`](#then) を使ってください。

## detected

画像の一致度や明るさなどを条件にする場合に使います。

```yaml
type: detected
minimum_score: 0.9
detector: {type: mean_brightness}
```

| 設定項目 | 必須・任意 | 指定する値 |
| --- | --- | --- |
| `minimum_score` | 必須 | しきい値。NaNや無限大を除く数値。 |
| `detector` | 必須 | [Detector](detectors.md)の種類と設定。 |

Detectorのスコアが `minimum_score` 以上で成立します。スコアの範囲は0〜1です。しきい値を0にすると有効なスコアはすべて成立し、1より大きくすると成立しません。

Monitorでは最新スコアと、リセット後の最大スコアを確認できます。Detectorが判定に失敗すると `error` になり、Ruleのエラー回数が増えます。

## all

経過時間と画像検出など、複数の条件を同時に満たす必要がある場合に使います。

```yaml
type: all
conditions:
  - {type: elapsed, duration: 1s}
  - {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

| 設定項目 | 必須・任意 | 指定する値 |
| --- | --- | --- |
| `conditions` | 必須 | すべて成立する必要があるConditionのリスト。 |

指定した条件がすべて成立するとtrueになります。空のリストもtrueになります。

リセットすると、リスト内のすべての条件もリセットします。

## any

複数の画面や待ち時間など、どれか1つの条件で操作できる場合に使います。

```yaml
type: any
conditions:
  - {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
  - {type: elapsed, duration: 10s}
```

| 設定項目 | 必須・任意 | 指定する値 |
| --- | --- | --- |
| `conditions` | 必須 | いずれかが成立すればよいConditionのリスト。 |

指定した条件が1つでも成立するとtrueになります。空のリストはfalseになります。

リセットすると、リスト内のすべての条件もリセットします。

## not

指定した明るさに届かない画面など、条件を満たさないことを調べる場合に使います。

```yaml
type: not
condition: {type: detected, minimum_score: 0.1, detector: {type: mean_brightness}}
```

| 設定項目 | 必須・任意 | 指定する値 |
| --- | --- | --- |
| `condition` | 必須 | 結果を反転するCondition。 |

指定した条件がfalseならtrueに、trueならfalseになります。

リセットすると、指定した条件もリセットします。

## rising_edge

画像が現れたときや、画面がしきい値以上に明るくなったときに使います。

```yaml
type: rising_edge
condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

| 設定項目 | 必須・任意 | 指定する値 |
| --- | --- | --- |
| `condition` | 必須 | 成立したかを調べるCondition。 |

指定した条件が前回の判定でfalse、今回の判定でtrueになったときだけ成立します。

初回の判定では比較の基準だけを記録し、falseになります。リセット時には比較の記録を消し、指定した条件も初期状態に戻します。

## falling_edge

画像が消えたときや、画面がしきい値より暗くなったときに使います。

```yaml
type: falling_edge
condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

| 設定項目 | 必須・任意 | 指定する値 |
| --- | --- | --- |
| `condition` | 必須 | 不成立になったかを調べるCondition。 |

指定した条件が前回の判定でtrue、今回の判定でfalseになったときだけ成立します。

初回の判定では比較の基準だけを記録し、falseになります。リセット時には比較の記録を消し、指定した条件も初期状態に戻します。

## once

先に特定の画面を通過したことなどを記録するときに使います。

```yaml
type: once
condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

| 設定項目 | 必須・任意 | 指定する値 |
| --- | --- | --- |
| `condition` | 必須 | 一度成立したことを記録するCondition。 |

指定した条件が一度でも成立すると、リセットするまでtrueを保ちます。

リセットすると成立した記録が消え、指定した条件もリセットします。

## elapsed

判定を始めてから一定時間待つ場合に使います。

```yaml
type: elapsed
duration: 3s
```

| 設定項目 | 必須・任意 | 指定する値 |
| --- | --- | --- |
| `duration` | 必須 | 待ち時間。[時間表現](yaml-reference.md#時間表現)で指定。 |

初めて判定した時点から計測し、経過時間が `duration` 以上になると成立します。`0s` なら初回の判定で成立し、成立後はリセットするまでtrueを保ちます。

リセットすると開始時刻と経過時間の記録が消えます。次の判定から測り直します。

## hold

短いちらつきで操作しないように、画面が一定時間続くのを待つ場合に使います。

```yaml
type: hold
duration: 500ms
condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

| 設定項目 | 必須・任意 | 指定する値 |
| --- | --- | --- |
| `duration` | 必須 | 成立が続く必要のある時間。[時間表現](yaml-reference.md#時間表現)で指定。 |
| `condition` | 必須 | 継続を調べるCondition。 |

指定した条件が初めてtrueになったときから測り、その後の判定でも成立が続いて `duration` 以上になるとtrueになります。falseを確認すると計測を取り消し、次にtrueになったときから測り直します。

`0ms` では指定した条件と同じ結果になります。リセットすると開始時刻と経過時間の記録が消え、指定した条件もリセットします。

## nth

画像が3回現れたときなど、回数を条件にする場合に使います。

```yaml
type: nth
count: 3
condition:
  type: rising_edge
  condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

| 設定項目 | 必須・任意 | 指定する値 |
| --- | --- | --- |
| `count` | 必須 | 1以上の整数。 |
| `condition` | 必須 | 成立した判定を数えるCondition。 |

指定した条件がtrueだった判定を数え、`count` 回目だけ成立します。trueが続く場合は判定ごとに1回ずつ数えます。途中でfalseになっても回数を保持します。

画像の出現回数を数えるには、例のように `rising_edge` を組み合わせます。リセットすると回数と成立した記録が消え、指定した条件もリセットします。

## reset_when

暗転したときに、それまでに画像を検出した記録を消す場合などに使います。

```yaml
type: reset_when
condition:
  type: once
  condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
reset_condition:
  type: not
  condition: {type: detected, minimum_score: 0.1, detector: {type: mean_brightness}}
```

| 設定項目 | 必須・任意 | 指定する値 |
| --- | --- | --- |
| `condition` | 必須 | 結果を調べるCondition。 |
| `reset_condition` | 必須 | リセットする時点を決めるCondition。 |

`reset_condition` が成立したフレームでは、両方の条件をリセットしてから `condition` を判定します。その判定で条件が成立すれば、同じフレームでtrueになります。

`reset_when` 自体がリセットされた場合も、指定した両方の条件をリセットします。

## then

画像を検出したあとに一定時間待つなど、順に条件を満たしてから1つの操作を行う場合に使います。

```yaml
type: then
within: 5s
conditions:
  - {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
  - {type: elapsed, duration: 1s}
```

| 設定項目 | 必須・任意 | 指定する値 |
| --- | --- | --- |
| `conditions` | 必須 | 成立を確認する順に並べたConditionのリスト。1件以上。 |
| `within` | 任意 | 最初の条件が成立してから残りを終えるまでの制限時間。[時間表現](yaml-reference.md#時間表現)で指定し、省略時は無制限。 |

現在の条件が成立すると次へ進み、その条件を後続のフレームで判定します。最後の条件が成立するとtrueになり、リセットまで保持します。例の1秒は、2つ目の条件を初めて判定した時点から測ります。

`within` を超えたら最初のステップに戻り、そのフレームから判定します。指定時間とちょうど同じ場合は期限内です。

期限切れで戻るのはステップの進行だけです。子Conditionの時間、回数、成立した記録は残ります。`then` 自体をリセットしたときは、進行と完了の記録、制限時間の計測、すべての子Conditionをリセットします。

ステップごとに操作を行う場合は[RuleSequence](yaml-reference.md#ruleとsequence)を使います。
