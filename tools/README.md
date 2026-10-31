# AutoSplit変換ツール

AutoSplitの `settings.toml` と画像列から、DivergenceSplitterで使用するScenario YAMLと参照画像のコピーを生成します。C++アプリケーションやWindows ZIPのビルドとは独立した補助ツールです。

Python 3.11以上とTkinterが必要です。追加のPythonパッケージは不要です。リポジトリのルートで実行します。

```powershell
python tools/converter_entry.py
```

AutoSplit settings.tomlで入力設定を選び、Output scenarioで保存先を指定してConvertを押します。YAMLの隣に `<保存名>_assets/` が生成されるため、参照画像と一緒に保管してください。変換処理は `autosplit_converter.py`、画面の起動は `converter_entry.py` が担当します。

変換対象はStart／Reset画像、Split画像の順序、対応する比較方式などです。すべてのAutoSplit設定を再現するわけではありません。出力の `Import result` と、必要に応じて `convert()` の戻り値に含まれる未変換項目・手動修正項目を確認してください。`loop_splits` や比較前のResizeなどには制限があります。

生成したYAMLは[C++版の設定検証](../cpp/docs/troubleshooting.md#cliでの確認)と代表的な映像で確認し、[YAMLリファレンス](../cpp/docs/scenarios/yaml-reference.md)に沿って調整してください。
