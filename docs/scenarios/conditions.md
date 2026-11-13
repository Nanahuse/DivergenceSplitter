# Conditionリファレンス

[シナリオ作成](README.md) · [YAMLのリセット](yaml-reference.md#状態とリセット)

Conditionはタイマーを操作する条件です。YAMLの `type` に、以下の12種類のいずれかを指定します。

別の条件と組み合わせるときは、`condition` に1つの条件を、`conditions` に条件のリストを書きます。各条件は `type` とその設定項目をひとまとまりにして記述します。省略できると書かれていない項目は必須です。未定義の項目があると読み込みに失敗します。

## 条件IDと上書きできる設定

すべてのConditionに任意の `id` を付けられます。上書き対象のルートや子条件にIDを付け、`overrides` のキーとして使います。時間や回数などの実行時の状態は使用箇所ごとに独立しています。

- `duration`、`count`、`minimum_score`、`within` など、そのConditionが持つ設定を変更できます。
- Detectorでは `reference`、`roi`、`hash_size`、色範囲など、そのDetectorが持つ設定を変更できます。
- Conditionの `type` と `id`、Detectorの `type`、子条件を指定する `conditions`、`condition`、`reset_condition` は固定です。子条件の設定を変更するには、その子のIDを直接指定します。

継承構文と `null` の扱いは[YAMLリファレンス](yaml-reference.md#conditionの継承)を参照してください。

## 時間・回数・状態の扱い

時間はLiveSplitのタイマーではなく、アプリ側の時計で測ります。Pauseしたり映像が途切れたりしても、計測中の時間は進みます。ただし、条件が成立したかを確認するのは、次のフレームを判定したときです。映像が来ない間は判定結果を更新しません。`hold` で条件が続いているかを確認できるのも、判定したフレームだけです。

複数の条件を組み合わせても、他の条件がfalseの間に時間の計測や回数の記録が進む場合があります。`all` に `nth` やedgeの条件を入れた場合は、それらが成立した瞬間に、他の条件も成立している必要があります。後から他の条件が成立しても、すでに過ぎた回数や変化を使い直すことはできません。

条件を順番に確認したい場合は、[`then`](#then) を使ってください。

## detected

```yaml
type: detected
minimum_score: 0.9
detector: {type: mean_brightness}
```

Detectorのスコアが `minimum_score` 以上ならtrueになります。しきい値と同じスコアでも成立します。

`minimum_score` と `detector` は必須です。`minimum_score` には、NaNや無限大を除く数値を指定します。`detector` には、使うDetectorの `type` と設定を記述してください。

すべてのDetectorのスコアは `[0, 1]` です。しきい値自体に範囲の制限はありませんが、1より大きくすると成立せず、0ならすべての有効なスコアで成立します。

Monitorには最新スコアと、リセット後に記録した最大スコアを表示します。リセットすると両方の記録が消えます。Detectorの判定に失敗した場合はfalseではなく `error` となり、Ruleのエラー回数が増えます。

## all

```yaml
type: all
conditions:
  - {type: elapsed, duration: 1s}
  - {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

指定した条件がすべて成立するとtrueになります。条件のリストを `conditions` に記述してください。この項目は必須です。空のリストならtrueになります。

リセットすると、リスト内のすべての条件もリセットします。

## any

```yaml
type: any
conditions:
  - {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
  - {type: elapsed, duration: 10s}
```

指定した条件が1つでも成立するとtrueになります。条件のリストを `conditions` に記述してください。この項目は必須です。空のリストならfalseになります。

リセットすると、リスト内のすべての条件もリセットします。

## not

```yaml
type: not
condition: {type: detected, minimum_score: 0.1, detector: {type: mean_brightness}}
```

指定した条件の結果を反転します。その条件がfalseならtrueに、trueならfalseになります。反転したい条件を、必須項目の `condition` に記述してください。

リセットすると、指定した条件もリセットします。

## rising_edgeとfalling_edge

```yaml
type: rising_edge
condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

`rising_edge` は条件がfalseからtrueに変わったときに成立します。`falling_edge` はtrueからfalseに変わったときに成立します。どちらも、変化を調べる条件を `condition` に記述します。この項目は必須です。

直前の判定と比べるため、読み込み後やリセット後の初回判定は、比較の基準を記録してfalseになります。最初からtrueでも `rising_edge` は成立せず、最初からfalseでも `falling_edge` は成立しません。

trueになるのは、変化を確認したその1回だけです。リセットすると、直前の値の記録を消し、指定した条件もリセットします。`falling_edge` を使う場合は、例の `type` を `falling_edge` に変えてください。

## once

```yaml
type: once
condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

指定した条件が一度でもtrueになると、リセットするまでtrueを保ちます。後でその条件がfalseに戻っても、`once` はtrueのままです。

判定する条件を、必須項目の `condition` に記述してください。1フレームだけtrueにしたい場合の条件ではありません。

リセットすると「一度成立した」という記録を消し、指定した条件もリセットします。次にその条件が成立するまでは、trueになりません。

## elapsed

```yaml
type: elapsed
duration: 3s
```

指定した時間が経つとtrueになります。待つ時間を、必須項目の `duration` に[時間表現](yaml-reference.md#時間表現)で指定してください。

計測を始めるのは、読み込み後またはリセット後に、この条件を初めて判定した時点です。ファイルを読んだ時刻やApplyを押した時刻から数えるわけではありません。タイマー開始や区間への移動と同時に初めて判定した場合は、その時点が計測開始になります。

経過時間が `duration` 以上になるとtrueになり、リセットするまでtrueを保ちます。`0s` なら初回の判定で成立します。リセットすると、開始時刻と経過時間の表示を消し、次の判定から測り直します。

## hold

```yaml
type: hold
duration: 500ms
condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

条件が指定時間だけ続くとtrueになります。必須項目の `condition` に判定する条件を、`duration` に必要な時間を記述してください。

最初にtrueになったときから計測し、その後の判定もtrueのまま `duration` 以上続くと成立します。1回でもfalseを確認すると、その時点でfalseに戻り、計測を取り消します。次にtrueになった時点から改めて時間を測ります。

一度成立しても、指定した条件がfalseに戻れば `hold` もfalseに戻ります。`0ms` の場合は、指定した条件と同じ結果になります。リセットすると開始時刻と経過時間の表示を消し、指定した条件もリセットします。

## nth

```yaml
type: nth
count: 3
condition:
  type: rising_edge
  condition: {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
```

指定した条件がtrueになった回数を数え、指定回数に達したときに成立します。必須項目の `count` に1以上の整数を、`condition` に数えたい条件を記述してください。

数えるのは、その条件がtrueだった判定の回数です。trueのフレームが続けば、フレームごとに1回ずつ数えます。途中でfalseになっても、回数は消えません。`count` 回目だけtrueになり、それ以降はリセットするまでfalseです。

画像が現れた回数を数えたい場合は、例のように `rising_edge` を組み合わせてください。画像が表示され続けている間は、何度も数えなくなります。リセットすると回数と成立済みの記録を消し、指定した条件もリセットします。

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

リセット用の条件と、結果を調べたい条件を組み合わせます。どちらも必須で、`reset_condition` にリセットの条件、`condition` に結果を調べる条件を記述します。

`reset_condition` が成立したフレームでは、両方の条件をリセットしてから `condition` を判定します。この判定で成立すれば、リセットと同じフレームでもtrueになります。リセットを理由に必ずfalseにしたり、次のフレームまで待ったりはしません。

`reset_when` 自体をリセットした場合も、指定した両方の条件をリセットします。

## then

```yaml
type: then
within: 5s
conditions:
  - {type: detected, minimum_score: 0.8, detector: {type: mean_brightness}}
  - {type: elapsed, duration: 1s}
```

条件をリストに書いた順番で確認します。すべてを順に満たすとtrueになります。必須項目の `conditions` に、空でない条件のリストを記述してください。

現在の条件がtrueになると、次のステップへ進みます。次の条件を調べるのは、その後のフレームからです。falseなら同じステップで待ちます。条件が1つなら、その条件が初めてtrueになったときに完了します。

`within` には、残りのステップを終えるまでの制限時間を指定できます。省略すると時間制限はありません。複数のステップがある場合は、最初の条件が成立した時点から計測します。各ステップに別々の制限時間を与える設定ではありません。

経過時間が `within` を超えると、次のフレームの判定で最初のステップに戻ります。そのフレームで最初の条件が成立していれば、再び次へ進みます。経過時間が `within` とちょうど同じなら、期限内です。

期限切れで戻るのはステップの進行だけです。各条件の計測や回数、成立済みの記録は消えません。以前の `elapsed` の計測、`once` の成立、`nth` の回数が、やり直した後の結果に影響する場合があります。

最後の条件まで成立するとtrueになり、リセットするまでtrueを保ちます。リセットすると、ステップの進行、制限時間の計測、完了の記録を消し、すべての条件もリセットします。

例の1秒は2つ目の条件である `elapsed` の判定を始めてから測ります。最初の条件が成立した瞬間から数えるわけではありません。

`then` は、複数の条件を順に確認して1つの操作を行うための条件です。ステップごとに別の操作を行いたい場合は、[RuleSequence](yaml-reference.md#ruleとsequence)を使ってください。
