# ビルドとテスト

Windows の x64 Native Tools Command Prompt または Visual Studio の Developer PowerShell を使います。MSVC と Windows SDK、CMake 3.25 以上、Ninja、Git、Python 3.10 以上を用意し、セットアップ済みの vcpkg のディレクトリを環境変数 `VCPKG_ROOT` に設定してください。Scenario Builder のビルドには Node.js 22 以上と npm が必要です。SDK の場所を指定しない場合、CMake が WebView2 SDK を取得します。

リポジトリのルートで構成、ビルド、テストを順に実行します。次の例では DivergenceSplitter のデバッグ版をビルドします。

```powershell
cmake --preset full
cmake --build --preset full --parallel
ctest --preset full
```

| プリセット | ビルド対象 |
| --- | --- |
| `core` / `core-release` | ライブラリとテストの Debug / Release ビルド |
| `full` / `full-release` | DivergenceSplitter とテストの Debug / Release ビルド |
| `builder` | Scenario Builder とテストの Debug ビルド |
| `ci` | 両アプリとテストの Release ビルド。LiveSplit.Bridge TestHost 用テストもビルドします |

実行ファイルは `build/<preset>/` に生成されます。Scenario Builder のビルドでは React のビルド成果物を `ScenarioBuilder.exe` と同じ階層の `scenario-builder-ui/` に配置します。フロントエンドのテストは [`apps/scenario-builder/frontend/`](../apps/scenario-builder/frontend) で `npm test` を実行してください。

## Windows ZIP

- DivergenceSplitter 単体は `full-release` のビルド後に `cmake --build --preset full-release --target package` を実行します。
- 両アプリの同梱版は `ci` のビルド後に `cmake --build --preset ci --target package` を実行します。
- Scenario Builder 単体は `builder` を `-DCMAKE_BUILD_TYPE=Release` 付きで構成してビルドします。次のコマンドで空の配布先にインストールし、ZIP にまとめます。

```powershell
cmake --install build/builder --prefix build/scenario-builder-dist --component ScenarioBuilder
Compress-Archive -Path "build/scenario-builder-dist/*" -DestinationPath "build/ScenarioBuilder-windows-x64.zip"
```

## ソースの配置

- [`apps/divergencesplitter/`](../apps/divergencesplitter) に Windows UI とアイコン、[`apps/scenario-builder/`](../apps/scenario-builder) に WebView2 ホストと React フロントエンドがあります。
- [`libs/`](../libs) の `core` は判定とシナリオを扱い、`capture` はカメラ、動画、NDI 入力を扱います。`runtime` はシナリオ実行と LiveSplit との接続、`scenario-editor` はシナリオ編集を担当します。公開ヘッダーは各ライブラリの `include/divergencesplitter/` にあります。
- [`tests/`](../tests) にはモジュールごとのテスト、アプリやライブラリを組み合わせた統合テスト、共通のテスト補助コードがあります。
