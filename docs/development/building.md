# ビルド

[開発ガイド](README.md) · [テスト](testing.md) · [配布](distribution.md)

## 必要な環境

Windows x64向けに次を用意してください。

- Visual Studio 2022または2026のC++デスクトップ開発ワークロードとWindows SDK、C++23対応のMSVCを使います。x64 Developer PowerShellで実行します。
- PATHから呼び出せるCMake 3.25以上とNinja。
- bootstrap済みの [vcpkg](https://github.com/microsoft/vcpkg)。`VCPKG_ROOT` に絶対パスを設定します。
- ビルドと配布ヘルパー向けのPython 3.10以上。coreだけをビルドする場合も、CMakeの設定時にPythonが必要です。必要な場合は `-DPython3_EXECUTABLE=C:/tools/python/python.exe` で指定してください。
- 初回の依存関係とBridge取得に使うgitとネットワーク接続。

依存ライブラリは [vcpkg.json](../../vcpkg.json) に記述し、builtin baselineでバージョンの基準を固定しています。OpenCV 4のCore・Imgproc・Imgcodecs・Videoioと付属の画像・カメラ機能、rapidyaml（ryml）とc4core、nlohmann/json、Boost.Asio・Beastを取得します。

GUIはDear ImGuiを使います。Dear ImGuiはvcpkgではなくFetchContentで固定タグ（既定は `v1.91.9b`）から取得し、Win32バックエンドとDirect3D 11バックエンドをアプリへ静的リンクします。Qtは使いません。`tests` featureを選ぶとGoogleTestを追加します。hash Detectorのためにopencv_contribを追加する必要はありません。

NDI入力のアダプターは常にビルドします。NDI SDKのヘッダーは [third_party/ndi/include](../../third_party/ndi/include) に固定版を同梱しているため、ビルド環境にNDI SDKを用意する必要はありません。NDI Runtimeは実行時の任意依存で、NDI入力を使う場合だけ別途インストールします。配布ZIPにはNDI Runtimeを含めません。

## 設定・ビルド・起動

リポジトリのルートからDeveloper PowerShellで実行します。

```powershell
$env:VCPKG_ROOT = 'C:/vcpkg'
cmake --preset full
cmake --build --preset full --parallel
ctest --preset full --output-on-failure
.\build\full\DivergenceSplitter.exe
```

依存関係、特にDear ImGuiの取得・ビルドに時間がかかります。ビルドされたDLLは実行ファイルの隣に置かれたまま使ってください。Qtプラグインの配置は不要です。問題が起きた場合は[トラブルシューティング](../troubleshooting.md)を参照してください。

UIなしでcore・runtimeを開発する場合は次を使います。

```powershell
cmake --preset core
cmake --build --preset core --parallel
ctest --preset core --output-on-failure
```

## プリセットとオプション

全プリセットはNinjaと `VCPKG_ROOT` のtoolchainを使います。ビルド先はプリセットごとに `build/<preset>` へ分かれます。コマンドはリポジトリのルートで実行してください。

| プリセット | 構成 | UI | vcpkg feature |
| --- | --- | --- | --- |
| `core` | Debug | 無効 | `tests` |
| `core-release` | Release | 無効 | `tests` |
| `full` | Debug | 有効 | `tests` |
| `full-release` | Release | 有効 | `tests` |
| `ci` | Release | 有効 | `tests`。TestHostテストも有効。 |

| CMakeオプション | 既定値 | 動作 |
| --- | --- | --- |
| `DIVERGENCESPLITTER_BUILD_UI` | `ON` | Dear ImGui UIとGUI実行ファイルをビルド。 |
| `DIVERGENCESPLITTER_BUILD_TESTS` | `ON` | GoogleTestを使ってテストをビルド・登録。 |
| `DIVERGENCESPLITTER_BUILD_TESTHOST_TESTS` | `OFF` | テスト有効時に実Bridge用の任意の結合テスト実行ファイルを追加。 |
| `DIVERGENCESPLITTER_FETCH_BRIDGE` | `ON` | Bridgeクライアントを取得・ビルド。OFFでは親ビルドが `livesplit_bridge::livesplit_bridge` を用意する必要があります。 |
| `DIVERGENCESPLITTER_BRIDGE_TAG` | `v0.1.0` | FetchContentで取得するタグ・コミット。 |
| `DIVERGENCESPLITTER_IMGUI_TAG` | `v1.91.9b` | FetchContentで取得するDear ImGuiのタグ・コミット。 |

Bridgeクライアントのソースが手元にある場合は、`-DFETCHCONTENT_SOURCE_DIR_LIVESPLIT_BRIDGE=C:/src/livesplit-bridge-client-cpp` で指定できます。再現性を確認するときは、指定されている固定バージョンのソースを使ってください。

アプリ側のターゲットは `divergencesplitter_core`、`divergencesplitter_runtime` です。UIを有効な場合、`divergencesplitter_imgui`、`divergencesplitter_ui`、`DivergenceSplitter` がビルドされます。製品CLIは削除済みで、テスト実行ファイルとGUIの起動試験だけを残します。

## NDI Runtime（実行時の任意依存）

NDI入力を使用する場合だけ、NDI RuntimeをNDI公式サイトからインストールしてください。DivergenceSplitterは起動時にインストール済みRuntimeを検出し、見つからない場合はNDI入力だけを無効にします。Camera・Video入力とその他の機能は通常どおり動作します。

- Runtimeの検索には `NDILIB_REDIST_FOLDER`（通常は `NDI_RUNTIME_DIR_V6`）と `NDILIB_LIBRARY_NAME` を使用し、一般的なインストール先も確認します。
- DLLの読み込み、`NDIlib_v5_load`、初期化の成功を確認します。失敗した場合は理由をProfileに表示します。
- 起動後にRuntimeをインストールした場合、再起動後に再判定します。
- 配布ZIPには `Processing.NDI.Lib.x64.dll` を含めません。アプリのディレクトリへDLLを置く運用は前提にしていません。

NDIの初期化・受信を自動テストする場合、CIは固定SDKからRuntime DLLだけを取得し、`NDI_RUNTIME_DIR_V6` をそのフォルダーへ向けてループバックテストを実行します。SDKのヘッダーはビルドに使いません。Secretがないfork PRではRuntimeテストをスキップし、Runtime未導入の起動・Camera・Video動作を検証します。

## ビルドで問題が起きた場合

- コンパイラーやWindows SDKがない場合、x64 Developer PowerShellを開き直してください。
- toolchainがない場合、`VCPKG_ROOT` とbootstrapを確認してからconfigureします。
- Dear ImGuiの取得に失敗する場合、gitとGitHubへの接続を確認するか、`-DDIVERGENCESPLITTER_IMGUI_TAG` を利用可能な固定タグへ変更します。取得済みソースを使う場合は `-DFETCHCONTENT_SOURCE_DIR_IMGUI=<path>` を指定できます。
- NDI入力を利用できない場合、NDI Runtimeがインストールされているか、`NDI_RUNTIME_DIR_V6` が正しいか確認し、アプリを再起動してください。ProfileのNDI入力設定で状態を確認できます。

依存関係、コンパイラー、SDKを変える場合は別のビルドディレクトリか新しいプリセットを使い、古いキャッシュの混入を避けてください。パッケージ化に必要な追加の通知は[配布ガイド](distribution.md)を参照してください。
