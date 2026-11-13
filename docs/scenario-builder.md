# Scenario Builder PoC

Scenario Builder は、DivergenceSplitter の YAML シナリオを GUI で編集するための
WebView2 + React の検証用アプリです。既定ではビルドされず、従来の
DivergenceSplitter とテストには影響しません。

## 目的

- 共通 Condition（YAML の `&anchor` / `*anchor`）の作成と再利用
- `extends` と `overrides` による使用箇所ごとの設定変更
- Condition ツリーの追加・削除・並べ替え
- YAML の読み書きと、DivergenceSplitter の実行用ローダーとの互換性確認
- Undo / Redo と保存・再読み込み

## ビルド

```powershell
cmake --preset builder
cmake --build --preset builder --target ScenarioBuilder
.\build\builder\ScenarioBuilder.exe
```

`DIVERGENCESPLITTER_BUILD_SCENARIO_BUILDER=ON` のときだけ、WebView2 SDK の
NuGet パッケージと React フロントエンドをビルドします。Node.js と npm が必要です。
WebView2 SDK を事前に展開している場合は
`DIVERGENCESPLITTER_WEBVIEW2_ROOT` に `build/native` を含むディレクトリを指定できます。

従来のビルドとテストではオプションは OFF のままです。

```powershell
cmake --preset full
cmake --build --preset full
ctest --preset full
```

## 構成

| 層 | 内容 |
| --- | --- |
| `src/scenario_editor` | YAML 非解決インポート、編集モデル、コマンド、Undo / Redo、YAML エクスポート |
| `src/scenario_builder` | Win32 + WebView2 ホスト、JSON IPC、ファイルダイアログ |
| `frontend/scenario-builder` | React + TypeScript + Vite の 3 ペイン UI |
| `tests/scenario_editor_tests.cpp` | モデル、YAML 往復、実行用ローダー互換性のテスト |

編集モデルと履歴の正本は C++ 側にあります。React は表示と操作状態を担当し、
変更は `{ "type": "command", "command": { ... } }` の JSON メッセージで送ります。
ホストは変更後のドキュメント全体を `state` メッセージで返します。

## YAML の扱い

- インポート時は `ryml::Tree::resolve()` を呼ばず、アンカーとエイリアスを保持します。
- 共通定義は `definitions` 配下に `&name` 付きで保存します。
- 直接参照は `*name`、使用箇所ごとの変更は `extends: *name` と `overrides` で保存します。
- 条件配列の順序、スカラー値、Detector 設定を保持します。
- コメント、空白、インデントは保持しません。
- YAML マージキー `<<` はインポート時に内容へ展開します。エディタからは
  アンカー参照または `extends` として保存されます。

保存した YAML は DivergenceSplitter の既存ローダーでそのまま読み込めます。
`tests/scenario_editor_tests.cpp` の `ExportedYamlLoadsInTheRuntimeLoader` で検証しています。

## UI

- 左ペイン: 共通定義、Start / Reset / Incomplete、Split 一覧
- 中央ペイン: Condition ツリー、Rule 一覧。Condition はドラッグ＆ドロップまたは
  上下ボタンで並べ替え
- 右ペイン: 選択 Condition の設定、共通定義への参照、`extends` の `overrides`

## PoC の制限

- 映像・カメラ・NDI の入力、プレビュー、Detector 実行は行いません。
- ROI を画像上で選択する機能はありません。数値で編集します。
- Rule Sequence の条件は表示できますが、ステップの追加・編集は限定的です。
- 既存 Dear ImGui UI とは統合していません。
- コメントや書式の完全維持、完成版の配布物・インストーラーは対象外です。
