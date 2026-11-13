# YAMLリファレンス

[シナリオ作成](README.md) · [Condition](conditions.md) · [Detector](detectors.md) · [例](examples.md)

## 目次

- [シナリオの構造](#シナリオの構造)
- [Ruleとsequence](#ruleとsequence)
- [Action](#action)
- [評価順序](#評価順序)
  - [区間内のRuleの評価順序](#区間内のruleの評価順序)
  - [操作を送るタイミング](#操作を送るタイミング)
- [状態とリセット](#状態とリセット)
- [時間表現](#時間表現)
- [パス](#パス)
- [Conditionの継承](#conditionの継承)
- [YAMLのアンカー・エイリアス・マージ](#yamlのアンカーエイリアスマージ)
  - [アンカーとエイリアス](#アンカーとエイリアス)
  - [マージ](#マージ)

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
| `splits` | はい | LiveSplitの区間順に並べたリスト。自動操作を設定する区間がなければ空リストを指定できます。 |
| `reset_condition` | いいえ | Running／Pausedのときに `reset` を要求するCondition。省略または `null` で無効にします。 |
| `incomplete_condition` | いいえ | 終了後に `undo` を要求するCondition。誤った最終Splitを戻す用途などに使います。省略または `null` で無効にします。 |

`splits` の各項目がLiveSplitの1区間に対応します。自動操作を設定する区間には `rules` を記述し、手動で操作する区間には `null` を指定してください。`null` は、その区間を自動でSkipする指定ではありません。`rules: []` も、自動操作のない区間になります。

シナリオの区間数がLiveSplitより少ない場合は、残りの区間に自動Ruleがないものとして扱います。逆に多い場合は、シナリオの判定を無効にします。ただし、区間が空でタイマーも停止しているRunは一時的に許容し、状態が変わったときに区間数を確認し直します。

Condition・Detectorの `type` とAction名は、大文字・小文字を区別します。区間、Rule、Condition、Detector、ROIには、定義された項目だけを書いてください。未定義の項目があると、読み込みに失敗します。

例外として、最上位にはアンカー定義やメタデータを追加できます。追加した項目だけで操作が増えることはありません。一方、省略可能な最上位項目の名前を間違えても、追加項目として無視される場合があります。必須項目は正しい名前と形式で記述する必要があります。

## Ruleとsequence

Ruleは条件と操作を組にした設定です。`condition` にConditionの設定を、`action` に操作名を記述します。この2項目以外は指定できません。条件がtrueになると、その操作を要求します。

条件ごとに違う操作を順番に行いたい場合は、`sequence` にRuleのリストを記述します。リストは空にできません。sequenceの中にさらにsequenceを置いたり、1つのRuleにActionの配列を指定したりはできません。

```yaml
sequence:
  - condition: {type: elapsed, duration: 1s}
    action: pause
  - condition: {type: elapsed, duration: 2s}
    action: resume
  - condition: {type: elapsed, duration: 1s}
    action: split
```

上の `sequence` 全体を、区間の `rules` の1項目として記述します。この設定をRuleSequenceと呼びます。現在のステップのRuleが操作を要求すると、次のステップへ進みます。次のRuleの判定はその後のフレームから始まります。最後まで進むと、リセットされるまで操作を要求しません。

ステップは操作を要求した時点で進みます。操作の失敗やタイマー状態の変化で、[進行がリセットされる](#状態とリセット)場合があります。

後のステップも同じ区間で実行したい場合は、区間を離れるSplit、Skip、Undo、Resetを最後に置いてください。同じ区間のままPause／Resumeした場合は、通常、sequenceの進行を保ちます。

複数の条件を順に確認し、最後に1つだけ操作を行う場合は、[`then`](conditions.md#then)を使います。RuleSequenceは各ステップに操作を持ちますが、`then` は1つのConditionです。

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

Actionに引数や遅延を付けたり、スクリプトやゲーム内時間の操作を指定したりする機能はありません。操作まで時間を置きたい場合はConditionを使ってください。全シナリオに共通するReaction time (ms)は[Settings](../user-guide.md#settings)で説明します。

## 評価順序

映像が届き、Bridgeとタイマーの状態を確認できているときは、次のグループを判定します。

| タイマーのPhase | 評価するグループ |
| --- | --- |
| Not running | `start_condition` だけ。 |
| Running／Paused | `reset_condition` を先に評価し、Resetが成立しなければ現在の区間のRule。 |
| Ended | `incomplete_condition` だけ。 |

Pausedの間も、時間条件と現在の区間のRuleを判定します。LiveSplitを一時停止しても、時間条件の計測は止まりません。現在のPhaseに対応しないグループは判定しません。

### 区間内のRuleの評価順序

同じ区間に複数のRuleがある場合は、記述順に確認し、最初に操作を要求したRuleを採用します。エラーになったRuleはMonitorで確認できます。そのフレームでは次のRuleの評価に進みます。

条件が成立したままだと、区間を移動しないPauseやResumeなどを再び要求する場合があります。一度だけ操作したい場合は、`rising_edge` など状態が変わったときだけ成立するConditionや、`sequence` を使います。

### 操作を送るタイミング

自動操作を送るまでの待ち時間は、[Settings](../user-guide.md#settings)のReaction time (ms)で設定します。通常の操作を送るまで、または結果を確認するまでは、次の通常の操作を開始しません。

Running／Pausedでは、通常の操作を送るまでの待ち時間や、Split／Skipの結果を待つ間も、自動Resetの条件を判定します。通常の操作をまだ送っていない間にResetが成立すると、その操作を取り消し、追加の待ち時間を置かずにResetを送ります。手動Resetも追加の待ち時間なしで送ります。Resetの結果を待つ間は、新しい操作を開始しません。

Bridgeが操作を受け付けた後の表示や、結果を確認できない場合の対処は[操作の確定待ちとResetの失敗](../troubleshooting.md#操作の確定待ちとresetの失敗)を参照してください。

## 状態とリセット

Conditionが記録する時間や回数は、インスタンスごと、記述した場所ごとに独立しています。同じアンカーを参照していても共有しません。

リセットすると、そのConditionと、その中に組み合わせた条件をすべてリセットし、表示を `not_evaluated` に戻します。何を消して、いつ判定を始め直すかは[Conditionリファレンス](conditions.md)で説明します。

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

`elapsed.duration`、`hold.duration`、`then.within` には、0以上の数値に `ms` または `s` を続けた文字列を指定します。たとえば `0ms`、`500ms`、`1.5s` です。小数点の前の数字は省略できないため、`.5s` ではなく `0.5s` と書いてください。引用符で囲むかどうかは任意です。

単位のない数値、負数、符号、空白、指数表記、分の指定、`1m30s` のような単位を組み合わせた指定は使えません。時間条件は通常、指定時間以上で成立します。ただし `then.within` の期限切れは、指定時間と同じ時点ではなく、それを超えた時点です。

## パス

シナリオには `.yaml` または `.yml` を使います。拡張子の大文字・小文字は区別しません。Profileにはシナリオの絶対パスを保存します。

Detectorの `reference` には絶対パスも相対パスも使えます。相対パスはYAMLファイルの保存先を基準にします。Profileの保存先や、アプリを起動したフォルダーが基準になるわけではありません。include、glob、環境変数、ホームディレクトリの展開には対応していません。

Windowsでも `images/title.png` や `C:/game/title.png` のようにスラッシュで区切れます。バックスラッシュで書く場合は、YAMLの単一引用符で囲むと、そのままの文字として保持されます。

参照画像はチャンネル数やビット深度を保って読み込みます。[画像の制約](detectors.md#参照画像とチャンネル)も確認してください。

## Conditionの継承

`extends: *anchor` は、アンカーで指定した1つのConditionを読み込み、任意の `overrides` を適用するDivergenceSplitterの機能です。開始・リセット・未完了の条件、Ruleの条件、複合条件内の子条件で使用できます。アンカーは `definitions` など任意の場所に置けます。

```yaml
definitions:
  base: &base
    id: wait
    type: elapsed
    duration: 1s

start_condition:
  extends: *base
  overrides:
    wait:
      duration: 2s
splits: []
```

- `id` には空でない文字列を指定します。継承元の条件ツリーでは、ルートとすべての子条件を通じてIDを一意にします。
- `overrides` はIDから設定へのマッピングです。マッピング同士はフィールドごとに再帰的にマージし、スカラーや配列は値全体を置き換えます。
- 省略可能な設定に `null` を指定すると、継承した値が解除されます。例えば `then` の `within` やDetectorの `roi` を省略時の動作に戻せます。
- 多段継承では元の定義に近い上書きから適用します。継承するConditionにも `id` を指定でき、省略時は継承元ルートのIDを引き継ぎます。
- `extends` と同じ階層には `overrides` と `id` を指定できます。設定項目の変更には `overrides` を使います。

`*anchor` をConditionとして直接使うと定義全体を参照します。`<<` はマッピングのキーを取り込みます。`extends` はさらに、配列内を含む子条件をIDで指定して設定を変更できます。[上書きできる項目](conditions.md#条件idと上書きできる設定)と[区間ごとに参照画像を切り替える例](examples.md#条件の継承で区間ごとの画像を指定)を参照してください。

## YAMLのアンカー・エイリアス・マージ

### アンカーとエイリアス

同じ条件やDetectorの設定を何度も書く場合は、YAMLのアンカーとエイリアスを使えます。`&name` で設定に名前を付け、`*name` でその設定を参照します。

アンカーは最上位以外にも定義できます。同じ名前が複数ある場合は、参照する位置より前にある、最後の定義を使います。

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

例の最上位項目 `bright` は共通設定を定義するためだけに置いています。これ自体は判定条件を追加しません。参照先が同じでも、各場所の `once` などが記録する状態は独立し、時間や回数を共有しません。

### マージ

共通設定の一部だけを変えたい場合は、`<<: *name` で設定を取り込んだ後、変更する項目を記述します。この取り込みをマージと呼びます。入れ子になった設定でも使えます。

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

マージで同じキーが重なった場合は、rapidyaml 0.16.0の優先順位に従います。単一のマージで値を上書きするときは、変更する項目を必ず `<<` の後に書いてください。前に書いた項目は取り込む設定で上書きされます。

`<<: [*a, *b]` のように複数の設定を取り込む場合は、後ろの `b` が優先されます。この場合、`<<` の後に明記した項目も後から取り込む設定で上書きされることがあります。YAML 1.1のマージ定義にある「明記した値が常に優先」「リストの先頭が優先」という規則とは異なるため、注意してください。

複数の設定を取り込んだ結果を確実に上書きしたい場合は、いったん結果にアンカーを付けてください。そのアンカーを単一のマージで取り込んでから、値を変えます。

```yaml
a: &a {type: detected, minimum_score: 0.2}
b: &b {minimum_score: 0.8, detector: {type: mean_brightness}}
combined: &combined {<<: [*a, *b]}
start_condition:
  <<: *combined
  minimum_score: 0.95
splits: []
```

マージはキーと値のひとまとまりごとに行います。入れ子になったDetectorの一部を変えたい場合は、そのDetectorの設定内にも `<<` を記述してください。

マージキーはYAML 1.2の基本仕様には含まれず、rapidyamlが対応する拡張機能として使います。エイリアスやマージを使った設定にも、必須項目、未定義のキー、型、値について同じ制約が適用されます。

元のYAMLでキーが重複している場合は、読み込みを拒否します。存在しないアンカー、循環する参照、キーと値のまとまり以外を取り込むマージは、YAMLエラーです。取り込んだ後の内容がシナリオの形式に合わない場合は、スキーマエラーになります。どちらのエラーでも、アプリ自体は終了しません。
