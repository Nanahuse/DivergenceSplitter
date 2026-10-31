# シナリオ作成

[日本語（正本）](README.md) | [English](README.en.md)

[ドキュメント一覧](../../README.md)

シナリオは `.yaml` または `.yml` ファイルです。開始条件、任意のReset条件・終了後の復帰条件、LiveSplitの区間ごとのRuleを記述します。Profileでファイルを同じPCのBridgeポートと映像入力に対応付けます。

1. [はじめに](../getting-started.md)の手順で[最小シナリオ](../../examples/minimal-scenario.yaml)を試します。
2. [YAMLリファレンス](yaml-reference.md)で構造、Action、評価順序、パス、アンカー、リセットを確認します。
3. [Detector](detectors.md)を選び、`detected` と必要な[Condition](conditions.md)で条件を組み立てます。
4. [例](examples.md)を調整してApplyし、[Diagnostics](../user-guide.md#diagnostics)でスコアを確認します。

座標の基準をそろえてください。入力のCrop／Resizeの後にDetectorのROIを適用します。参照画像のResizeはProfileの別の設定です。[設定リファレンス](../configuration.md#cropresize参照画像)を参照してください。

正規化したフレームが届き、インスタンスが有効なBridge状態を持つときだけシナリオを評価します。時間条件はLiveSplitの実時間・ゲーム内時間ではなく、アプリの単調増加時刻を使います。次の評価がなければ成立結果も更新されません。

公開スキーマは [scenario_loader.cpp](../../src/core/scenario_loader.cpp) に実装されています。ConditionとDetectorの動作は[テスト](../development/testing.md)でも確認できます。
