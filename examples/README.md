# サンプルシナリオ

自動操作を試す場合は、先に [はじめに](../docs/getting-started.md) の手順で映像と LiveSplit を接続してください。

## 時間で Start と Split を試す

[scenario-v2.yaml](scenario-v2.yaml) は、開始条件の判定から2秒後に Start し、最初の区間の判定から3秒後に Split します。参照画像は不要です。LiveSplit には1区間のテスト用 Run を用意します。

- そのまま試すには、DivergenceSplitter の「Profile」で「Scenarios & Connections」を開きます。「Browse」でダウンロードしたファイルを選び、「Apply」を押します。
- 設定を確認・変更するには、Scenario Builder の「作業フォルダ」でファイルを保存したフォルダーを指定し、左側の「YAML」でファイルを選びます。

[はじめに](../docs/getting-started.md)で使う [minimal-scenario.yaml](minimal-scenario.yaml) でも同じ動作を試せます。

## 画像が映ったら Start し、消えたら Split する

1. [image-scenario.yaml](image-scenario.yaml) と [reference.ppm](reference.ppm) を同じフォルダーに保存します。LiveSplit には1区間のテスト用 Run を用意します。
2. DivergenceSplitter の「Profile」でサンプルを選びます。入力の「Resize」を使っている場合は「Resize reference images」をオフにします。そのあと「Apply」を押します。
3. 入力映像に参照画像と同じ模様を映します。Start したあとも、最初の区間で模様が検出されるまで映し、検出されたら画面から消します。判定結果は[Monitor](../docs/user-guide.md#判定結果とグラフ)で確認できます。

## 共通 Condition で区間ごとに参照画像を変える

[scenario-v2-shared.yaml](scenario-v2-shared.yaml) を保存し、Scenario Builder で開きます。2つの区間で同じ画像判定の条件を使い、参照画像だけを切り替える例です。

サンプルには参照画像が付属していません。動作を試す場合は、左側の「共通Condition」の `course_finish` で既定の画像を選び、「Split 1」と「Split 2」の Rule では各区間の画像を選び直してください。シナリオを保存して、LiveSplit の2区間のテスト用 Run で実行できます。参照画像の選び方は [画像が映ったら Split する](../docs/scenario-builder.md#画像が映ったら-split-する) を参照してください。
