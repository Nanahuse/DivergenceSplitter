# サンプルファイル

[ドキュメント一覧](../README.md) · [シナリオ例](../docs/scenarios/examples.md)

## 目次

- [経過時間でStartとSplitを試す](#経過時間でstartとsplitを試す)
- [画像の出現と消失を検出する](#画像の出現と消失を検出する)

どちらのサンプルも、映像入力と、同じPCで動作するLiveSplit.Bridgeが必要です。LiveSplitに1区間のテスト用Runを用意します。

## 経過時間でStartとSplitを試す

[minimal-scenario.yaml](minimal-scenario.yaml) は、開始条件の判定から2秒後にStartし、最初の区間の判定から3秒後にSplitします。参照画像は不要です。[はじめに](../docs/getting-started.md)の手順で設定できます。

動画入力を使う場合は、[profile.example.json](profile.example.json) も使えます。`source.path` を10秒より長い録画の絶対パスに、`instances[0].scenario` を保存したYAMLの絶対パスに書き換えます。Bridgeで `54000` 以外のポートを使う場合は、`instances[0].connection.port` も合わせます。ProfileのOpenでJSONを開くと、その設定で実行を始めます。

## 画像の出現と消失を検出する

[image-scenario.yaml](image-scenario.yaml) は、参照画像が映るとStartし、最初の区間でその画像が消えるとSplitします。

1. [image-scenario.yaml](image-scenario.yaml) と [reference.ppm](reference.ppm) を同じフォルダーに保存します。参照画像は読み込み確認用の8×8の模様です。
2. ProfileのインスタンスでこのYAMLを指定し、Resize reference imagesをオフにしてApplyを押します。サンプルのJSONを使う場合は、Openの前に `instances[0].scenario` をこのYAMLの絶対パスに変えます。
3. 入力映像に参照画像と同じ模様を表示します。Startした後も、最初の区間で検出されるまで模様を表示し、検出されたら画面から消します。判定結果は[Monitor](../docs/user-guide.md#判定結果とグラフ)で確認できます。

ゲームで使う場合は参照画像を置き換え、映像に合わせてしきい値を調整してください。設定の説明は[画像の検出](../docs/scenarios/examples.md#画像の検出)を参照してください。
