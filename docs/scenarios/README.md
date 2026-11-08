# シナリオ作成

[日本語（正本）](README.md) | [English](README.en.md)

[ドキュメント一覧](../../README.md)

シナリオは、自動操作の条件を記述した `.yaml` または `.yml` ファイルです。いつStartするか、各区間でいつSplitなどの操作をするかを指定します。必要に応じて、自動Resetの条件や、Run終了後に最後のSplitを取り消す条件も設定できます。

Profileでは、このファイル、映像入力、同じPCで動くLiveSplitのBridgeポートを組み合わせます。シナリオでは、次の用語を使います。

| 用語 | 意味 |
| --- | --- |
| Detector | 画像を調べ、一致度や明るさなどをスコアにする判定方法です。 |
| Condition | スコア、経過時間、検出回数などから、条件が成立したかを判定します。 |
| Action | Start、Split、Resetなど、LiveSplitに送る操作です。 |
| Rule | ConditionとActionの組です。条件が成立すると、その操作を要求します。 |

1. [はじめに](../getting-started.md)の手順で[最小シナリオ](../../examples/minimal-scenario.yaml)を試します。
2. [YAMLリファレンス](yaml-reference.md)で構造、Action、評価順序、パス、アンカー、リセットを確認します。
3. [Detector](detectors.md)を選び、`detected` と必要な[Condition](conditions.md)で条件を組み立てます。
4. [例](examples.md)を調整してApplyし、[Monitor](../user-guide.md#monitor)でスコアを確認します。

画像の位置を指定するときは、Crop／Resize後の画像を基準にしてください。DetectorのROIはその画像のどこを調べるかを指定するものです。参照画像自体のサイズを変える設定は別にあります。詳しくは[設定リファレンス](../configuration.md#cropresize参照画像)を参照してください。

シナリオを判定するには、入力映像が届き、接続先のタイマーの状態を確認できている必要があります。時間を使う条件も、映像のフレームを判定するときに結果を更新します。詳しくは[Conditionリファレンス](conditions.md#時間回数状態の扱い)を参照してください。

設定の実装や検証に関わる開発者は、[ローダー](../../src/core/scenario_loader.cpp)と[テスト手順](../development/testing.md)を参照してください。
