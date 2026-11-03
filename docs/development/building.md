# ビルド

[開発ガイド](README.md) · [テスト](testing.md) · [配布](distribution.md)

## 必要な環境

Windows x64向けに次を用意してください。

- Visual Studio 2022または2026のC++デスクトップ開発ワークロードとWindows SDK。C++23対応のMSVCを使い、x64 Developer PowerShellで実行します。
- PATHから呼び出せるCMake 3.25以上とNinja。
- bootstrap済みの [vcpkg](https://github.com/microsoft/vcpkg)。`VCPKG_ROOT` に絶対パスを設定します。
- ビルド・配布用ヘルパー向けのPython 3.10以上。Coreだけをビルドする場合も、CMakeの設定時にPythonが必要です。必要なら `-DPython3_EXECUTABLE=C:/tools/python/python.exe` で指定してください。
- 初回の依存関係・Bridge取得に使うGitとネットワーク接続。

依存ライブラリは [vcpkg.json](../../vcpkg.json) に記述し、builtin baselineでバージョンの基準を固定しています。OpenCV 4のCore・Imgproc・Imgcodecs・Videoioと指定した画像・カメラ機能、rapidyaml（ryml）とc4core、nlohmann/json、Boost.Asio／Beastを取得します。

`tests` featureを選ぶとGoogleTestを、`ui` を選ぶとQt 6 qtbaseを追加します。hash Detectorのためにopencv_contribを追加する必要はありません。

## 設定・ビルド・起動

リポジトリのルートからDeveloper PowerShellで実行します。

```powershell
$env:VCPKG_ROOT = 'C:/vcpkg'
cmake --preset full
cmake --build --preset full --parallel
ctest --preset full --output-on-failure
.\build\full\DivergenceSplitter.exe
```

初回は依存ライブラリもビルドするため、時間がかかります。特にQtのビルドは長くなります。生成されたDLLとQtプラグインは、実行ファイルの隣に置いたまま使ってください。

Debugでは、CMakeがデバッグ用プラグインをコピーします。Releaseでは、`windeployqt` が見つかれば、それを使って配置します。CLIは `build/full/divergencesplitter-cli.exe` です。[使い方](../troubleshooting.md#cliでの確認)も参照してください。

Qtなしでcore／runtimeを開発する場合は次を使います。

```powershell
cmake --preset core
cmake --build --preset core --parallel
ctest --preset core --output-on-failure
```

## プリセットとオプション

全プリセットはNinjaと `VCPKG_ROOT` のtoolchainを使います。ビルド先はプリセットごとに `build/<preset>` へ分けます。コマンドはリポジトリのルートで実行してください。

| プリセット | 構成 | UI | vcpkg feature |
| --- | --- | --- | --- |
| `core` | Debug | 無効 | `tests` |
| `core-release` | Release | 無効 | `tests` |
| `full` | Debug | 有効 | `tests;ui` |
| `full-release` | Release | 有効 | `tests;ui` |
| `ci` | Release | 外部Qtを使用 | `tests`。TestHostテストも有効。 |

`ci` プリセットでは、インストール済みのQtを `CMAKE_PREFIX_PATH` または `Qt6_DIR` で指定します。workflowはvcpkgでQtをビルドせず、外部のQt 6.8.3 MSVC 2022 x64を使います。

ローカルでも同じ構成を使う場合は、configure時に `-DCMAKE_PREFIX_PATH=C:/Qt/6.8.3/msvc2022_64` などを指定し、アーキテクチャを合わせてください。UIを有効にする場合は、Qt WidgetsとQt Testの両方が必要です。

| CMakeオプション | 既定値 | 動作 |
| --- | --- | --- |
| `DIVERGENCESPLITTER_BUILD_UI` | `ON` | Qt UIとGUI実行ファイルをビルド。 |
| `DIVERGENCESPLITTER_BUILD_TESTS` | `ON` | GoogleTestを使ってテストをビルド・登録。 |
| `DIVERGENCESPLITTER_BUILD_TESTHOST_TESTS` | `OFF` | テスト有効時に実Bridge用の任意の結合テスト実行ファイルを追加。 |
| `DIVERGENCESPLITTER_FETCH_BRIDGE` | `ON` | Bridgeクライアントを取得・ビルド。OFFでは親ビルドが `livesplit_bridge::livesplit_bridge` を用意する必要があります。 |
| `DIVERGENCESPLITTER_BRIDGE_TAG` | `v0.1.0` | FetchContentで取得するタグ・コミット。 |
| `DIVERGENCESPLITTER_ENABLE_NDI` | `OFF` | Windows x64で公式SDKの受信機を有効化。 |
| `NDI_SDK_DIR` | 空 | NDI有効時の展開済みSDKルート。 |

Bridgeクライアントのソースが手元にある場合は、`-DFETCHCONTENT_SOURCE_DIR_LIVESPLIT_BRIDGE=C:/src/livesplit-bridge-client-cpp` で指定できます。再現性を確認するときは、指定されている固定バージョンのソースを使ってください。

アプリ側のターゲットは `divergencesplitter_core`、`divergencesplitter_runtime`、`divergencesplitter_cli` です。UIが有効な場合は、`divergencesplitter_ui` と `DivergenceSplitter` もビルドします。

## NDI対応ビルド

NDIは既定でOFFです。通常の開発ではSDKを用意する必要がありません。ONにする場合は、[ndi-sdk-lock.json](../../tools/ndi-sdk-lock.json) の固定値に一致する公式SDKを使います。現在の固定バージョンは6.3.2.0です。

Windows用SDKをinnoextractで展開し、`Include`、`Bin/x64`、`NDI SDK License Agreement.pdf` が入っているフォルダーを `NDI_SDK_DIR` に指定してください。SDKの開発用ファイルやインストーラーはコミットしません。

```powershell
cmake --preset full-release -DDIVERGENCESPLITTER_ENABLE_NDI=ON -DNDI_SDK_DIR=C:/private/ndi-sdk/app
cmake --build --preset full-release --parallel
ctest --preset full-release --output-on-failure
.\build\full-release\divergencesplitter-cli.exe --ndi-check
.\build\full-release\divergencesplitter-cli.exe --ndi-list
```

NDI有効時はWindows x64が必要です。SDKには `Processing.NDI.Lib.h`、`Processing.NDI.DynamicLoad.h`、ランタイムDLL、ランタイム通知、確認済みの契約書が必要です。不足するファイルがある場合や、DLL・通知・契約書のハッシュが固定値と違う場合は、configureに失敗します。

DLLは実行ファイルの隣へコピーし、その絶対パスから読み込みます。別の場所にインストールされたランタイムで代用することはありません。CIでの取得と検証は[配布](distribution.md#ci-workflow)を参照してください。

## ビルドの問題

- コンパイラーやWindows SDKがない場合は、x64 Developer PowerShellを開き直してください。
- toolchainがない場合は `VCPKG_ROOT` とbootstrapを確認してからconfigureします。
- Qtがない場合は `full` でvcpkgからビルドするか、`ci` に外部Qtのパスを渡します。DebugとReleaseのDLL・プラグインを混在させないでください。
- NDIのハッシュが合わない場合は固定SDKを使ってください。検証を無効化するのではなく、固定値を更新する際にSDKと通知を確認します。

依存関係、コンパイラー、SDKを変える場合は別のビルドディレクトリやプリセットを使い、古いキャッシュの混入を避けてください。パッケージ化に必要な追加の通知は[配布ガイド](distribution.md)を参照してください。
