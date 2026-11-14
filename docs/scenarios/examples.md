# シナリオ例

[シナリオ作成](README.md) · [YAMLリファレンス](yaml-reference.md)

## 目次

- [時間待ち](#時間待ち)
- [画像の検出](#画像の検出)
- [条件を順に確認する](#条件を順に確認する)
- [複数の条件を組み合わせる](#複数の条件を組み合わせる)
- [複数のActionを順に実行する](#複数のactionを順に実行する)
- [条件の継承で区間ごとの画像を指定](#条件の継承で区間ごとの画像を指定)
- [明るい画面の出現回数を数える](#明るい画面の出現回数を数える)

各例を `.yaml` ファイルに保存し、Profileで指定します。映像が届き、BridgeがReadyになると判定を始めます。LiveSplitには、例の `splits` に合わせた区間数のテスト用Runを用意してください。

## 時間待ち

[はじめに](../getting-started.md)で使う[最小シナリオ](../../examples/minimal-scenario.yaml)です。開始条件の判定を始めて2秒後にStartし、最初の区間の判定を始めて3秒後にSplitします。どちらの時間もその条件を最初に判定した時点から測ります。

```yaml
start_condition: {type: elapsed, duration: 2s}
splits:
  - rules:
      - condition: {type: elapsed, duration: 3s}
        action: split
```

## 画像の検出

指定した画像が映るとStartし、その画像が消えるとSplitする例です。消えたことを判定するには、最初の区間に入ってから、一度は画像が映っているフレームを確認する必要があります。

[reference.ppm](../../examples/reference.ppm)をYAMLと同じフォルダーに置きます。小さな参照画像をその寸法のまま探すため、ProfileのResize reference imagesをオフにします。

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

## 条件を順に確認する

明るい画面でStartした後、最初の区間で「暗い画面になり、その後、明るい画面が500ms続く」という順序を確認してSplitします。

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

## 複数の条件を組み合わせる

自動Startの後、最初の区間で「2秒以上経ったこと」と「ほぼ赤い画面が300ms続いたこと」の両方を満たすとSplitします。

2秒の経過と赤い画面の300msは並行して数えます。順番を指定する場合は、前の例のように `then` を使います。

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

## 複数のActionを順に実行する

最初の区間で1秒待ってPauseし、次の条件の判定を始めて2秒後にResumeし、さらに次の条件で1秒待ってSplitします。ステップごとに操作するには、例のようにsequenceを使います。

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

各区間で別の画像を検出し、1秒待ってからSplitします。待ち時間とDetectorの設定をアンカーにまとめ、`course` の参照画像を区間ごとに変更します。

LiveSplitには2区間を用意します。YAMLと同じフォルダーに `assets` フォルダーを作り、`YI1.png` と `DPC.png` を入れてください。それぞれの寸法とチャンネル数を判定対象の映像に合わせます。

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

## 明るい画面の出現回数を数える

明るさの設定をアンカーで共通化し、最初の区間で画面が暗い状態から明るい状態に変わる回数を数えます。3回目の変化でSplitします。

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

この例では、2区間目を手動で操作します。
