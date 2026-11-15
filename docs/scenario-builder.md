# Scenario Builder PoC

Scenario Builder は、DivergenceSplitter の YAML v2 シナリオを GUI で編集するための
WebView2 + React の検証用アプリです。既定ではビルドされず、従来の
DivergenceSplitter とテストには影響しません。

## 目的

- パラメーター付き共通 Condition / Detector の作成と再利用
- 使用箇所ごとの値変更を、ユーザーに ID やパスを入力させず自動パラメーター化
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

`cmake --build --preset builder --target ScenarioBuilder` の後、
`cmake --install build/builder --prefix <dir> --component ScenarioBuilder` で
実行ファイル、Web UI、必要な DLL、ライセンスをまとめて配置できます。

## 構成

| 層 | 内容 |
| --- | --- |
| `src/core/scenario_v2.cpp` | YAML v2 の共通定義・パラメーター解決（実行用と編集用で共有） |
| `src/scenario_editor` | 編集モデル、コマンド、Undo / Redo、YAML v2 入出力 |
| `src/scenario_builder` | Win32 + WebView2 ホスト、JSON IPC、ファイルダイアログ |
| `frontend/scenario-builder` | React + TypeScript + Vite の 3 ペイン UI |
| `tests/scenario_editor_tests.cpp` | 編集コマンド、パラメーター生成、保存、往復 |
| `tests/scenario_v2_tests.cpp` | ローダー v2 解決、循環・型検証、旧形式との一致 |

編集モデル、解決結果、履歴の正本は C++ 側にあります。React は表示と操作状態を担当し、
変更は `{ "type": "command", "command": { ... } }` の JSON メッセージで送ります。
ホストは変更後のドキュメントと解決済み Condition を `state` メッセージで返します。

## YAML v2

```yaml
schema_version: 2

definitions:
  conditions:
    course_finish:
      parameters:
        course_image: assets/default.png
      condition:
        type: then
        conditions:
          - type: detected
            minimum_score: 0.9
            detector:
              type: root_mean_square_similarity
              reference: {param: course_image}
          - type: elapsed
            duration: 1s

start_condition:
  type: elapsed
  duration: 0s

splits:
  - rules:
      - condition:
          use: course_finish
          with:
            course_image: assets/YI1.png
        action: split
  - rules:
      - condition:
          use: course_finish
          with:
            course_image: assets/DPC.png
        action: split
```

- `definitions.conditions` / `definitions.detectors` に共通定義を置きます。
- 各定義の `parameters` は既定値を持ちます。
- 設定値全体を `{param: name}` で参照できます。文字列置換ではありません。
- `use` は使用箇所から Condition / Detector の種類が決まります。種類が異なる参照はエラーです。
- `with` を省略した場合は既定値を使います。未知のパラメーターはエラーです。
- 定義の参照順序に依存しません。未定義参照、型不一致、循環参照は読み込み時に拒否します。

サンプルは [`examples/scenario-v2.yaml`](../examples/scenario-v2.yaml) と
[`examples/scenario-v2-shared.yaml`](../examples/scenario-v2-shared.yaml) にあります。

## 共通定義と使用箇所

- 共通定義の設定・条件追加・削除・順序変更は、すべての使用箇所に反映されます。
- 使用箇所の設定を変更すると、C++ が必要なパラメーターを共通定義に自動生成し、
  元の値を既定値として `with` に新しい値を保存します。
- パラメーター名は C++ が生成します。UI で名前や上書きパスを入力する必要はありません。
- 「共通定義の値に戻す」で使用箇所の `with` を削除できます。
- 使用箇所を共通定義から切り離す場合は、解決済み Condition をインライン化します。

旧形式（アンカー・エイリアス・`extends` / `overrides`）は DivergenceSplitter の
実行用ローダーで引き続き読み込めます。Scenario Builder の v2 編集および旧形式から
v2 への変換は段階的対応のため、現時点では旧形式ファイルを編集用に開くと明示的な
エラーになります。

## 作業ディレクトリと Asset

Scenario Builder は作業ディレクトリ単位で YAML と参照画像を管理します。

```text
C:\Scenarios\SuperMarioWorld\
├── Asset\
│   ├── YI1.png
│   ├── DPC.png
│   └── clear.png
├── SMW_11_Exit.yaml
└── SMW_96_Exit.yaml
```

- ツールバーの「作業フォルダ」から Windows 標準のフォルダー選択ダイアログで指定します。
- `Asset` がなければ自動作成します。
- YAML は作業ディレクトリ直下に保存し、ファイル名は自由に指定できます。
- 作業ディレクトリを開くと、直下の `.yaml` / `.yml` を一覧表示します。
- 別の YAML へは一覧から切り替えます。
- 参照画像は `Asset/DPC.png` のような、YAML からの相対パスで保存します。
- パス区切りは `/` に統一し、絶対パスは保存しません。
- Asset 内の画像は参照画像の選択欄から選びます。「新規追加」は標準のファイル選択
  ダイアログを開き、画像を検証してから `Asset` へコピーします。
- 同名の画像は上書きせず、`DPC_2.png` のような別名を自動生成します。
- 画像の追加は Undo / Redo の対象外です。参照先の変更だけが Undo / Redo の対象になります。
- 作業ディレクトリ・YAML・Asset の外へ出るパスや、シンボリックリンク経由の逸脱は拒否します。

共通Conditionのパラメーター既定値、共通Detectorの参照、使用箇所の `with` のどこで
画像を選択しても、同じ Asset 一覧から選択できます。使用箇所の画像を変更すると、
既存のパラメーター化の仕組みにより必要な `with` だけが更新されます。
## 保存と検証

- 編集コマンド適用時に C++ モデルと解決済み Condition を検証します。
- 保存時は同じディレクトリの一時 YAML に書き出し、既存の
  `load_scenario()` で読み込めることを確認します。
- 検証と書き込みが成功した場合だけ、一時ファイルを元のファイルへ置き換えます。
  失敗時は元のファイルを変更しません。
- ルート直下の `metadata` などの未知フィールドは保持し、保存時にも出力します。
- 引用符付きスカラーと `!!str` タグ付きスカラーは文字列として保持します。
  `"null"`、`"~"`、`!!str null` は引用符付きで出力し、null 値へ変化しません。
- 新規作成・ファイルを開く・ウィンドウを閉じるときは、未保存の変更について
  保存・破棄・キャンセルを確認します。

## UI

- 左ペイン: 作業ディレクトリ内のYAML一覧、共通Condition、共通Detector、Start / Reset / Incomplete、Split 一覧
- 中央ペイン: Condition ツリー、Rule 一覧。Condition はボタンまたはドラッグ＆ドロップで並べ替え
- 右ペイン: 選択 Condition の設定、共通定義の利用、Asset からの参照画像選択、使用箇所ごとの変更と解除

共通Conditionを使用している場合も、中央には解決済み Condition が通常のツリーとして
表示されます。右ペインで値を変更すると、その使用箇所の `with` が更新されます。

## PoC の制限

- 映像・カメラ・NDI の入力、プレビュー、Detector 実行は行いません。
- ROI を画像上で選択する機能はありません。数値で編集します。\n- Asset 内の画像削除は行いません。
- 使用箇所から、ネストした共通定義の内部構造は変更できません。共通定義側で編集します。
- Rule Sequence の条件は表示できますが、ステップ構造の編集は限定的です。
- 旧 YAML の編集用インポートと v2 への自動変換は未実装です。
- 既存 Dear ImGui UI とは統合していません。
- コメントや書式の完全維持、完成版の配布物・インストーラーは対象外です。
