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
`builder` プリセットは Scenario Builder 単体の検証用に
`DIVERGENCESPLITTER_BUILD_UI=OFF` としています。WebView2 SDK を事前に展開している場合は
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

編集モデル、YAML の解決結果、履歴の正本は C++ 側にあります。React は表示と
操作状態を担当し、変更は `{ "type": "command", "command": { ... } }` の JSON
メッセージで送ります。ホストは変更後のドキュメントと `extends` / `overrides`
適用済みの解決結果を `state` メッセージで返します。React 側では継承を再解決しません。

## YAML の扱い

- インポート時は `ryml::Tree::resolve()` を呼ばず、アンカーとエイリアスを保持します。
- 共通定義は `definitions` 配下に `&name` 付きで保存します。
- 直接参照は `*name`、使用箇所ごとの変更は `extends: *name` と `overrides` で保存します。
- 条件配列の順序、スカラー値、Detector 設定を保持します。
- ルート直下の未対応フィールド（`metadata` など）は、実行用ローダーが許容する
  追加データとしてそのまま保持し、保存時にも出力します。UI では編集しません。
- 引用符付きスカラーと `!!str` タグ付きスカラーは文字列として保持します。
  `"null"`、`"~"`、`!!str null` などは保存時に引用符付きで出力し、null 値へ
  変化しないようにします。
- コメント、空白、インデントは保持しません。
- YAML マージキー `<<` はインポート時に内容へ展開します。エディタからは
  アンカー参照または `extends` として保存されます。
- 条件や Detector の定義箇所に付いたアンカーは共通定義へ移し、元の使用箇所は
  `*anchor` 参照に置き換えます。これにより定義元と参照先の共有関係を維持します。
- ネストしたアンカーは依存関係を解決し、参照先の共通定義を先に出力します。
- スカラー・配列・マッピングキー・Split/Rule 構造に付いたアンカー、アンカー名の
  再定義は、共有関係を保持できないため読み込み時に明示的に拒否します。
- `extends` / `overrides` の解決規則と検証は実行用ローダーに合わせています。
  存在しない Override ID、重複 ID、不正な上書きフィールドはエラーになります。
- Condition / Detector の項目は型ごとの固定スキーマで管理します。未定義の項目、
  必須項目の欠落、型に合わない値は読み込み・編集コマンド・保存の各段階で拒否します。
- UI はスキーマに定義された項目だけを表示し、任意キーの追加はできません。
  省略可能な項目だけを既定値付きで追加できます。`overrides` の対象項目も
  Condition ID とスキーマから選択します。

## 保存

- 編集コマンド適用後に C++ モデルの参照関係を検証します。
- 保存時は同じディレクトリの一時 YAML に書き出し、既存の
  `load_scenario()` で読み込めることを確認します。
- 検証と書き込みが成功した場合だけ、一時ファイルを元のファイルへ置き換えます。
  失敗時は元のファイルを変更しません。
- 新規作成・ファイルを開く・ウィンドウを閉じるときは、未保存の変更について
  保存・破棄・キャンセルを確認します。

`tests/scenario_editor_tests.cpp` では、アンカー参照、ネストした Detector
アンカー、`extends` / `overrides`、無効な参照、保存失敗時のファイル保護、
実行用ローダーでの読み込みを検証しています。

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
