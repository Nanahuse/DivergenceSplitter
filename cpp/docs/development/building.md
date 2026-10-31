# ビルド

[日本語（正本）](building.md) | [English](building.en.md)

[開発ガイド](README.md) · [テスト](testing.md) · [配布](distribution.md)

## 必要な環境

Windows x64向けに次を用意してください。

- Visual Studio 2022または2026のC++デスクトップ開発ワークロードとWindows SDK。C++23対応のMSVCを使い、x64 Developer PowerShellで実行します。
- PATHから呼び出せるCMake 3.25以上とNinja。
- bootstrap済みの [vcpkg](https://github.com/microsoft/vcpkg)。`VCPKG_ROOT` に絶対パスを設定します。
- ビルド・配布用ヘルパー向けのPython 3.10以上。coreだけでもCMakeが必要とします。必要なら `-DPython3_EXECUTABLE=C:/tools/python/python.exe` で指定してください。
- 初回の依存関係・Bridge取得に使うGitとネットワーク接続。

[vcpkg.json](../../vcpkg.json) でbuiltin baselineを固定し、OpenCV 4のCore・Imgproc・Imgcodecs・Videoioと選択した画像・カメラ機能、yaml-cpp、nlohmann/json、Boost.Asio／Beastを取得します。`tests` featureはGoogleTest、`ui` はQt 6 qtbaseを追加します。hash Detectorにopencv_contribは不要です。

## 設定・ビルド・起動

リポジトリのルートからDeveloper PowerShellで実行します。

```powershell
$env:VCPKG_ROOT = 'C:/vcpkg'
cd cpp
cmake --preset full
cmake --build --preset full --parallel
ctest --preset full --output-on-failure
.\build\full\DivergenceSplitter.exe
```

初回は依存関係、とくにQtのビルドに時間がかかります。DLLと配置されたQtプラグインは実行ファイルの隣に保ってください。DebugではCMakeがdebug用プラグインをコピーします。Releaseでは利用可能なら `windeployqt` を使います。CLIは `build/full/divergencesplitter-cli.exe` です。[使用方法](../troubleshooting.md#cliでの確認)を参照してください。

Qtなしでcore／runtimeを開発する場合は次を使います。

```powershell
cmake --preset core
cmake --build --preset core --parallel
ctest --preset core --output-on-failure
```

## プリセットとオプション

全プリセットはNinjaと `VCPKG_ROOT` のtoolchainを使い、`cpp/build/<preset>` に分けて生成します。プリセットのコマンドは `cpp/` で実行してください。

| プリセット | 構成 | UI | vcpkg feature |
| --- | --- | --- | --- |
| `core` | Debug | 無効 | `tests` |
| `core-release` | Release | 無効 | `tests` |
| `full` | Debug | 有効 | `tests;ui` |
| `full-release` | Release | 有効 | `tests;ui` |
| `ci` | Release | 外部Qtを使用 | `tests`。TestHostテストも有効。 |

`ci` では `CMAKE_PREFIX_PATH` または `Qt6_DIR` からQtを見つけられる必要があります。workflowはvcpkgでQtをビルドせず、外部のQt 6.8.3 MSVC 2022 x64を使います。ローカルでも同じ構成にするなら、configure時に `-DCMAKE_PREFIX_PATH=C:/Qt/6.8.3/msvc2022_64` を指定し、アーキテクチャをそろえてください。UI有効時はQt WidgetsとQt Testの両方が必要です。

| CMakeオプション | 既定値 | 動作 |
| --- | --- | --- |
| `DIVERGENCESPLITTER_BUILD_UI` | `ON` | Qt UIとGUI実行ファイルをビルド。 |
| `DIVERGENCESPLITTER_BUILD_TESTS` | `ON` | GoogleTestを使ってテストをビルド・登録。 |
| `DIVERGENCESPLITTER_BUILD_TESTHOST_TESTS` | `OFF` | テスト有効時に実Bridge用の任意の結合テスト実行ファイルを追加。 |
| `DIVERGENCESPLITTER_FETCH_BRIDGE` | `ON` | Bridgeクライアントを取得・ビルド。OFFでは親ビルドが `livesplit_bridge::livesplit_bridge` を用意する必要があります。 |
| `DIVERGENCESPLITTER_BRIDGE_TAG` | `v0.1.0` | FetchContentで取得するタグ・コミット。 |
| `DIVERGENCESPLITTER_ENABLE_NDI` | `OFF` | Windows x64で公式SDKの受信機を有効化。 |
| `NDI_SDK_DIR` | 空 | NDI有効時の展開済みSDKルート。 |

既存クライアントを使う場合は `-DFETCHCONTENT_SOURCE_DIR_LIVESPLIT_BRIDGE=C:/src/livesplit-bridge-client-cpp` を指定できます。再現確認では所定の固定バージョンに合わせてください。アプリのターゲットは `divergencesplitter_core`、`divergencesplitter_runtime`、`divergencesplitter_cli` と、UI有効時の `divergencesplitter_ui`／`DivergenceSplitter` です。

## NDI対応ビルド

通常の開発でSDKを必要としないよう、NDIの既定値はOFFです。ONでは [ndi-sdk-lock.json](../../tools/ndi-sdk-lock.json) に一致する公式SDKを取得します。現在の固定値は6.3.2.0です。Windowsの内容をinnoextractで展開し、`Include`、`Bin/x64`、`NDI SDK License Agreement.pdf` があるディレクトリを `NDI_SDK_DIR` に指定してください。SDK開発用ファイルとインストーラーはコミットしません。

```powershell
cmake --preset full-release -DDIVERGENCESPLITTER_ENABLE_NDI=ON -DNDI_SDK_DIR=C:/private/ndi-sdk/app
cmake --build --preset full-release --parallel
ctest --preset full-release --output-on-failure
.\build\full-release\divergencesplitter-cli.exe --ndi-check
.\build\full-release\divergencesplitter-cli.exe --ndi-list
```

Windows x64、`Processing.NDI.Lib.h`、`Processing.NDI.DynamicLoad.h`、ランタイムDLL、ランタイム通知、確認済みの契約書が必要です。ファイル不足、DLL・通知・契約書の固定ハッシュとの不一致ではconfigureを失敗させます。DLLはビルドした実行ファイルの隣へコピーし、そこから絶対パスで読みます。別の場所にインストールしたランタイムでは代替しません。CIでの取得・検証は[配布](distribution.md#ci-workflow)を参照してください。

## ビルドの問題

- コンパイラーやWindows SDKがない場合は、x64 Developer PowerShellを開き直してください。
- toolchainがない場合は `VCPKG_ROOT` とbootstrapを確認してからconfigureします。
- Qtがない場合は `full` でvcpkgからビルドするか、`ci` に外部Qtのパスを渡します。DebugとReleaseのDLL・プラグインを混在させないでください。
- NDIのハッシュが合わない場合は固定SDKを使ってください。検証を無効化するのではなく、固定値を更新する際にSDKと通知を確認します。

依存関係、コンパイラー、SDKを変える場合は別のビルドディレクトリやプリセットを使い、古いキャッシュの混入を避けてください。パッケージ化に必要な追加の通知は[配布ガイド](distribution.md)を参照してください。
