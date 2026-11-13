# サンプルファイル

[ドキュメント一覧](../README.md) · [シナリオ例](../docs/scenarios/examples.md)

- [minimal-scenario.yaml](minimal-scenario.yaml)：開始条件の判定を始めて2秒後にStartし、区間0の判定を始めて3秒後にSplitします。画像を使わないため、参照画像は不要です。LiveSplitに1区間のテスト用Runを用意してください。
- [profile.example.json](profile.example.json)：このシナリオを動画入力で使うための、v2のProfileです。動画とYAMLのパスを、自分の環境の絶対パスに書き換えてください。動作を確認する時間を取るため、10秒より長い動画を使います。
- [image-scenario.yaml](image-scenario.yaml) と [reference.ppm](reference.ppm)：画像の検出を試す例です。2つを同じフォルダーに置くと読み込めます。参照画像は単色ではない小さな模様で、ゲーム用ではありません。実際に使うときはゲームの参照画像に置き換えてください。この例も1区間用です。

GUIでの操作は[はじめに](../docs/getting-started.md)を参照してください。変更済みProfileを確認するには、Profile画面でOpenしてApplyを押します。Applyはシナリオと参照画像を読み込み、入力設定を検証します。入力映像はPreview inputで確認できます。

JSONに書かれたサンプルのパスは、Windowsのパスとして正しい形式です。ただし、その場所にファイルがあるとは限りません。検証や再生の前に、実際の保存先へ書き換えてください。

画像の例を確認するときは、Profileの `scenario` を `image-scenario.yaml` の絶対パスに変えます。YAML内の参照画像のパスはYAMLの保存先を基準にした相対パスのままで使えます。
