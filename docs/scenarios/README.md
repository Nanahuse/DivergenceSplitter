# シナリオ作成

[ドキュメント一覧](../../README.md)

## 目次

- [シナリオの基本](#シナリオの基本)
- [作成と動作確認](#作成と動作確認)
- [関連ドキュメント](#関連ドキュメント)

## シナリオの基本

シナリオは、LiveSplitをいつ、どのように操作するかを記述したYAMLファイルです。Startの条件と区間ごとの操作に加えて、自動Resetや、Run終了後に最後のSplitを取り消す条件も設定できます。

| 用語 | 役割 |
| --- | --- |
| Detector | 映像を調べ、一致度や明るさなどをスコアで返します。 |
| Condition | スコア、経過時間、検出回数などから、条件が成立したかを判定します。 |
| Action | Start、Split、Resetなど、LiveSplitに要求する操作です。 |
| Rule | ConditionとActionの組です。条件が成立したときに操作を要求します。 |

## 作成と動作確認

1. [はじめに](../getting-started.md)に沿って、経過時間でStartとSplitを行うシナリオを試します。
2. [シナリオ例](examples.md)から目的に近い例を選び、`.yaml` または `.yml` に保存します。画像を使う場合は、調べたい範囲と目的に合う[Detector](detectors.md#方式の選び方)を選びます。
3. [YAMLリファレンス](yaml-reference.md#シナリオの構造)に沿って、操作したい区間とActionを決めます。[Condition](conditions.md)を選んで、操作する条件を記述します。
4. Profileで映像入力、Bridge port、シナリオのファイルを指定し、Applyを押します。映像が届き、BridgeがReadyになると判定を始めます。
5. [Monitor](../user-guide.md#monitor)で現在の区間と判定結果を確認します。画像を使う場合は、検出したい場面と誤検出しやすい場面のスコアを比べ、しきい値を調整してください。YAMLや参照画像を変更したら、もう一度Applyを押します。

## 関連ドキュメント

- [YAMLリファレンス](yaml-reference.md)で、記述形式、評価順序、状態がリセットされる条件を確認できます。
- [Conditionリファレンス](conditions.md)で、スコア・時間・回数を使う条件を選べます。
- [Detectorリファレンス](detectors.md)で、画像の比較方法、ROI、参照画像の制約を確認できます。
- [シナリオ例](examples.md)と[サンプルファイル](../../examples/README.md)には、試しやすい設定例があります。
- [トラブルシューティング](../troubleshooting.md#判定が成立しない意図せず成立する)で、判定結果が意図と異なる場合の確認手順を調べられます。
