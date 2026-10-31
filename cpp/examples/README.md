# サンプルファイル

[日本語（正本）](README.md) | [English](README.en.md)

[ドキュメント一覧](../README.md) · [シナリオ例](../docs/scenarios/examples.md)

- [minimal-scenario.yaml](minimal-scenario.yaml)：評価開始から2秒後にStartし、区間0の評価開始から3秒後にSplitします。参照画像は不要です。1区間のテストRunで使ってください。
- [profile.example.json](profile.example.json)：上のシナリオを使うv2のVideo Profileです。動画と保存したYAMLの両方の絶対パスを変更してください。10秒より長い再生可能な録画なら、確認する時間を確保できます。
- [image-scenario.yaml](image-scenario.yaml) と [reference.ppm](reference.ppm)：小さな一様でない画像でテンプレート検出を試す、読み込み可能な例です。2つを同じ場所に置き、ゲーム映像で使う前に実際の参照画像へ置き換えてください。こちらも1区間用です。

GUIでの操作は[はじめに](../docs/getting-started.md)を参照してください。入力を開かず、Bridgeへ接続せずに、変更済みProfileを確認するには次を使います。

```powershell
.\divergencesplitter-cli.exe --profile C:/DivergenceSplitter/profile.json --check
```

JSONのサンプルパスはWindowsの構文として有効ですが、シナリオの検証と動画再生には指定先に実ファイルが必要です。画像の例は `scenario` をそのYAMLの絶対パスに変更して確認します。YAML内の画像パスはYAML自身の保存場所を基準とする相対パスのまま使えます。
