# シナリオ例

[日本語（正本）](examples.md) | [English](examples.en.md)

[シナリオ作成](README.md) · [YAMLリファレンス](yaml-reference.md)

以下のYAMLはそれぞれ完全なシナリオです。`.yaml` として保存し、Profileに絶対パスを指定してください。画像の例は同梱の [reference.ppm](../../examples/reference.ppm) をYAMLの隣に置くと読み込めます。実用時はゲームの参照画像に置き換えてしきい値を調整してください。8×8の模様は読み込みの実演用であり、ゲーム画面を検出する画像ではありません。操作にはフレームの到着とBridgeのReady状態が必要です。

## 画像の検出

テンプレートを見つけると開始し、消えるとSplitします。最初の区間に入った後、`falling_edge` が一度「画像あり」を観測しないと消失を検出できません。小さなテンプレートを探索するため、ProfileのResize reference imagesはオフにします。

```yaml
start_condition:
  type: detected
  minimum_score: 0.95
  detector:
    type: template_match
    reference: reference.ppm
splits:
  - rules:
      - condition:
          type: falling_edge
          condition:
            type: detected
            minimum_score: 0.95
            detector:
              type: template_match
              reference: reference.ppm
        action: split
```

[image-scenario.yaml](../../examples/image-scenario.yaml) でも同じ判定を試せます。固定位置を比べるなら適切なROIと同寸法の参照を用意し、`mean_absolute_similarity` を使えます。[Detectorの制約](detectors.md)も確認してください。

## 時間待ち

[はじめに](../getting-started.md)で使う[最小シナリオ](../../examples/minimal-scenario.yaml)です。開始側の時計はStartを初めて評価したとき、Split側は区間0を初めて評価したときに始まります。

```yaml
start_condition: {type: elapsed, duration: 2s}
splits:
  - rules:
      - condition: {type: elapsed, duration: 3s}
        action: split
```

## 順に観測して1つのActionを実行

明るい画面で開始します。区間0では暗い画面を観測した後、明るい画面が500ms続くとSplitします。`within` は暗さの成立時から計測し、期限切れで子のHoldをリセットしません。子の状態も消す必要がある場合は [`reset_when`](conditions.md#reset_when) を使ってください。

```yaml
start_condition:
  type: detected
  minimum_score: 0.8
  detector: {type: mean_brightness}
splits:
  - rules:
      - condition:
          type: then
          within: 10s
          conditions:
            - type: not
              condition:
                type: detected
                minimum_score: 0.1
                detector: {type: mean_brightness}
            - type: hold
              duration: 500ms
              condition:
                type: detected
                minimum_score: 0.8
                detector: {type: mean_brightness}
        action: split
```

## 複数の条件

自動開始後、区間0で少なくとも2秒待ち、ほぼ赤い状態が300ms連続するとSplitします。先頭の `all` の子がfalseでもHoldは短絡評価で更新されます。elapsed成立後に必ず追加の300msを待つわけではありません。

```yaml
start_condition: {type: elapsed, duration: 2s}
splits:
  - rules:
      - condition:
          type: all
          conditions:
            - {type: elapsed, duration: 2s}
            - type: hold
              duration: 300ms
              condition:
                type: detected
                minimum_score: 0.9
                detector:
                  type: color_range
                  lower: [0, 0, 180]
                  upper: [80, 80, 255]
        action: split
```

## 複数のAction

区間0で1秒後にPauseし、次のRuleの評価開始から2秒後にResumeし、さらに次のRuleで1秒待ってSplitします。同じ位置のPhase遷移を確認できれば、Pause／Resumeでsequenceの位置を保ちます。外部Reset、再同期、区間を動かす操作は進行に影響します。[RuleSequence](yaml-reference.md#ruleとsequence)を参照してください。

```yaml
start_condition: {type: elapsed, duration: 2s}
splits:
  - rules:
      - sequence:
          - condition: {type: elapsed, duration: 1s}
            action: pause
          - condition: {type: elapsed, duration: 2s}
            action: resume
          - condition: {type: elapsed, duration: 1s}
            action: split
```

## アンカーによる共通化と出現回数

明るさの条件を共通化し、区間0でrising edgeを3回数えます。`rising_edge` がパルスを返すので、連続した明るいフレームは1回だけ数えます。リセット後の初回はedgeの基準値を記録します。ルートでアンカーを定義し、参照した各箇所の状態は独立します。

```yaml
bright: &bright
  type: detected
  minimum_score: 0.8
  detector: {type: mean_brightness}
start_condition: *bright
splits:
  - rules:
      - condition:
          type: nth
          count: 3
          condition:
            type: rising_edge
            condition: *bright
        action: split
  - null
```

最後の例はLiveSplitに最低2区間必要で、2区間目は手動です。Resetや誤った最終Splitからの復帰は、[ルートの仕様](yaml-reference.md#シナリオの構造)に従って `reset_condition` や `incomplete_condition` を追加してください。
