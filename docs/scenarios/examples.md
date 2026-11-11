# シナリオ例

[日本語（正本）](examples.md) | [English](examples.en.md)

[シナリオ作成](README.md) · [YAMLリファレンス](yaml-reference.md)

以下のYAMLはそのまま `.yaml` ファイルとして保存できるシナリオです。保存したファイルの絶対パスをProfileに指定してください。どの例でも、映像が届き、BridgeがReadyになってからタイマー操作を行います。

画像を使う例では、[reference.ppm](../../examples/reference.ppm)をYAMLと同じフォルダーに置くと読み込みを試せます。この8×8の模様は読み込み確認用です。ゲームで使うときは、実際の参照画像に置き換え、しきい値を調整してください。

## 画像の検出

指定した画像が映るとStartし、その画像が消えるとSplitする例です。消えたことを判定するには、最初の区間に入ってから、一度は画像が映っているフレームを確認する必要があります。

この例では、小さな参照画像を映像の中から探します。ProfileのResize reference imagesはオフにしてください。

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

[はじめに](../getting-started.md)で使う[最小シナリオ](../../examples/minimal-scenario.yaml)です。開始条件の判定を始めて2秒後にStartし、区間0の判定を始めて3秒後にSplitします。どちらの時間もその条件を最初に判定した時点から測ります。

```yaml
start_condition: {type: elapsed, duration: 2s}
splits:
  - rules:
      - condition: {type: elapsed, duration: 3s}
        action: split
```

## 順に観測して1つのActionを実行

明るい画面でStartした後、区間0で「暗い画面になり、その後、明るい画面が500ms続く」という順序を確認してSplitします。

暗い画面を確認してから10秒を超えた場合は、最初のステップからやり直します。ただし、各条件が記録した状態は期限切れだけでは消えません。詳しくは [`then`](conditions.md#then)を参照してください。

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

自動Startの後、区間0で「2秒以上経ったこと」と「ほぼ赤い画面が300ms続いたこと」の両方を満たすとSplitします。

赤い画面の300msは最初の2秒と重なっていても成立します。「2秒待ち、それから赤い画面を300ms待つ」という順序を指定した例ではありません。

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

区間0で1秒待ってPauseし、次の条件の判定を始めて2秒後にResumeし、さらに次の条件で1秒待ってSplitします。ステップごとに操作するには、例のようにsequenceを使います。

同じ区間のままPause／Resumeしたことを確認できれば、sequenceの進行を保ちます。外部からのReset、タイマーとの再同期、区間の移動では、進行がリセットされる場合があります。[RuleSequence](yaml-reference.md#ruleとsequence)も参照してください。

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

## 条件の継承で区間ごとの画像を指定

各区間で別の画像を検出し、1秒待ってからSplitします。待ち時間と検出器の設定をアンカーにまとめ、`course` の参照画像だけを区間ごとに変更します。

```yaml
definitions:
  course_finish: &course_finish
    type: then
    conditions:
      - id: course
        type: detected
        minimum_score: 0.9
        detector:
          type: root_mean_square_similarity
          reference: assets/default.png
      - type: elapsed
        duration: 1s

start_condition: {type: elapsed, duration: 0s}

splits:
  - rules:
      - condition:
          extends: *course_finish
          overrides:
            course:
              detector:
                reference: assets/YI1.png
        action: split
  - rules:
      - condition:
          extends: *course_finish
          overrides:
            course:
              detector:
                reference: assets/DPC.png
        action: split
```

## アンカーによる共通化と出現回数

明るさの設定をアンカーで共通化し、区間0で画面が暗い状態から明るい状態に変わる回数を数えます。3回目の変化でSplitします。

`rising_edge` は変化したフレームだけで成立するため、明るい画面が続いても1回と数えます。リセット後の最初のフレームは比較の基準として使い、変化としては数えません。同じアンカーを参照しても、各条件の記録は独立しています。

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
