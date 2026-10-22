# C++23 / Qt Widgets 配布容量検証

Python/Flet版との容量比較のための独立した実験。DivergenceSplitter本体、Scenario Runtime、完全なCondition/Detectorは移植しない。

最初はvcpkgの標準機能を有効にした `x64-windows` の動的リンクを使う。Qtは `qtbase` と `qtwebsockets`、OpenCVは `opencv4[contrib]` を採用する。QtのJSON APIを使用するため、別のJSONライブラリは追加しない。独自triplet、OpenCVの独自ビルド、サイズ優先の機能削除は行わない。

## 固定するもの

- vcpkg本体とregistry: `9e593bb18ea69cc5095e012465dcd675a822ed0d`（公式 `2026.07.29` タグのcommit）。
- Qt Base `6.11.1#1`、Qt WebSockets `6.11.1`、OpenCV `4.12.0#7`。直接依存はmanifestのoverride、推移依存はbaselineで固定する。
- Release、C++23、MSVC、Ninja、`x64-windows`。QtとOpenCVの標準default-featuresを維持する。Qtのデプロイツールのfeatureを追加する。
- 容量測定用PythonはCIで `3.14.6`。ZIPはDEFLATE level 6、固定時刻、パス順、同じルート名を使用する。

GitHubの `windows-2025` イメージやMSVC/SDKは更新されるため、バイト単位の同一ビルドは保証しない。利用したイメージ、MSVC、SDK、CMake、Ninja、portのstatusとSPDXを配布物の `build-metadata/` に記録する。ZIP比較はPython/zlibのバージョンまで一致している場合のみ生成する。

## 実行方法

Windows x64のVisual Studio C++ Developer PowerShell（PowerShell 7.3以上）、CMake 3.27以上、Ninja、Python 3.14が必要。

リポジトリルートから実行する。

```powershell
git clone https://github.com/microsoft/vcpkg.git build/vcpkg
git -C build/vcpkg checkout 9e593bb18ea69cc5095e012465dcd675a822ed0d
$env:VCPKG_ROOT = (Resolve-Path build/vcpkg).Path
& build/vcpkg/bootstrap-vcpkg.bat -disableMetrics

# 既存配布ArtifactのZIPを別途取得した場合
python tools/measure_distribution.py --source-zip current-windows.zip --output build/size-probe/legacy-report --kind legacy --label 'Python/Flet reference' --provenance 'run URL / commit / artifact ID'

& tools/build_cpp_size_probe.ps1
```

2回目以降はclone/bootstrapを省略できる。配布物への古いファイルの混入を避けるため、スクリプトは `dist/cpp-size-probe` が既に存在する場合に停止する。再測定はそのフォルダーを別名で保存するか、不要と確認して削除した後に行う。`--source-zip` の展開先も新規である必要がある。

CIは `.github/workflows/cpp-size-probe.yml` に同じ手順を実装する。初回はQt/OpenCVと標準依存のソースビルドで時間がかかる。vcpkgのbinary cacheはビルド時間の短縮だけに使い、測定対象には含めない。通常のPR/pushでは既知のmain配布run `38922970221` を比較元とする。Artifactの保存期限を過ぎた場合は、workflow_dispatchの `legacy_run_id` で新しい成功runを指定する。空欄ならC++単独測定となり、比較は未実施である。

## 実際に試す機能

- Qt Widgets: ウィンドウ、ボタン、チェックボックス、QImage/QPixmapによる画像プレビュー。
- OpenCV: PNG保存・再読込、グレースケール変換、リサイズ、ぼかし。
- Contrib: PHashの計算と同じ画像の距離比較。
- 動画: 実ファイルのMJPEG AVIを3フレーム生成し、VideoCaptureで読んで検証する。GUIから任意ファイルの先頭フレームも開ける。MP4/H.264の対応や実カメラ入力はこのテストの保証対象に含まない。
- 通信: localhostの一時ポートでWebSocket接続し、JSONメッセージを往復させて内容を照合する。外部サーバーは不要。
- NDI: 公式ヘッダーによる関数型を使用し、exe隣のDLLだけを明示的にロードして初期化・バージョン取得・終了を行う。NDIのimport libraryにはリンクしない。

`--self-test` は実際のWindowsウィンドウを表示した後、テストして終了する。失敗は非ゼロ、NDI未提供は明示的なUNVERIFIED。`--require-ndi` を付けると未提供は失敗となる。NDIを含む構成のCTestと配布起動テストは必ずこの引数を付ける。

## NDI SDKの取得・配布経路

[NDI公式SDK](https://ndi.video/for-developers/ndi-sdk/) から取得し、同梱契約と再配布対象を確認したSDKを使用する。既存のPython wheelからDLLを抜き出したり、第三者のヘッダーでABIを定義したりしない。

[公式ライセンス説明](https://docs.ndi.video/all/developing-with-ndi/sdk/licensing) はアプリ内へのDLL同梱、NDIサイトへのリンク、商標表記、同梱契約とthird-party rightsの遵守を案内している。[動的ロードの公式説明](https://docs.ndi.video/all/developing-with-ndi/sdk/dynamic-loading-of-ndi-libraries) も参照。検証GUIと同梱noticeにはサイトリンクと商標表記を含める。

ローカルでは次の環境変数を指定してビルドする。

```powershell
$env:NDI_SDK_DIR = 'C:/path/to/official/NDI SDK'
$env:NDI_LICENSE_FILE = 'C:/path/to/official/NDI SDK/the-original-sdk-agreement.pdf'
& tools/build_cpp_size_probe.ps1
```

`Include/Processing.NDI.Lib.h`、`Bin/x64/Processing.NDI.Lib.x64.dll`、`Bin/x64/Processing.NDI.Lib.Licenses.txt` と、そのSDKの契約ファイルが必要。SDKディレクトリーの他の内容は配布しない。

CIでNDIも検証する場合は、利用権限と契約を確認した同じファイル群を次のレイアウトのZIPに準備し、workflow_dispatchでURLとSHA256を指定する。SDK全体やヘッダーを公開Artifactへアップロードしない。この入力ZIPの管理場所・アクセス権はSDK契約に従う。

```text
Include/                         # 公式ヘッダー一式
Bin/x64/Processing.NDI.Lib.x64.dll
Bin/x64/Processing.NDI.Lib.Licenses.txt
SDK-license.pdf                  # 元の契約ファイル、内容は変更しない
```

スクリプトはSHA256照合後に展開する。個別のSDKの取得、契約確認、CIへの供給が未実施の場合はNDIをUNVERIFIEDとして除外する。公式の配布方式が確認できても、入力した特定バージョンの配布検証が成功したことを意味しない。NDIなしの成功を全構成の完了として扱わない。

## 配布・容量集計

CMake Install、Qt Deploy、CMakeの実行時依存スキャンで必要なDLLを収集する。Qtプラグインの依存もスキャンする。MSVC RuntimeはCMakeの `InstallRequiredSystemLibraries` でVisual Studioの再配布ディレクトリーからapp-local配置する（[Microsoftの配布説明](https://learn.microsoft.com/en-us/cpp/windows/choosing-a-deployment-method)）。System32や開発ツールのDLLは配布対象にしない。

Qt Deployが標準で収集する `d3dcompiler_47.dll`、`dxcompiler.dll`、`dxil.dll` はWindows SDKの `Redist/D3D/x64` とハッシュを照合する。SDK同梱の契約・第三者通知を収集し、容量はWindows SDK描画ランタイムとして別区分に計上する。収集元や文書を確認できない場合は配布検証を失敗させる（[Microsoftの再配布説明](https://learn.microsoft.com/en-us/windows/win32/directx-sdk--august-2009-)）。

配布検証は主要DLL、Windowsプラグイン、MSVC Runtime、port所有者、ライセンスを確認し、ヘッダー・静的ライブラリ・PDB・Debugディレクトリーを検出すると失敗する。vcpkgの全導入portのcopyrightとSPDXを保持するため、ビルド専用依存の文書分も保守的に含む。vcpkg baselineとSPDXに元ソースの参照を記録する。正式な製品配布時のソース提供手続きはこの容量実験の完了とは別途確認する。

配布exeはPATHから開発環境を除き、配布ディレクトリーをcwdとして再実行する。Qt/OpenCV設定用の環境変数も除外する。ただしWindows CIは完全な新規エンドユーザーPCではなく、OSのシステムDLLは利用する。

ファイル別CSV/JSON、区分別Markdown、ZIPを `build/size-probe/{legacy,cpp}-report/` に生成する。GitHub Actions自身の圧縮後サイズはZIP比較に用いず、生成した内側のZIPを測定する。外側のArtifact圧縮はlevel 0。

C++版の区分はvcpkgの導入ファイル一覧と依存グラフで求める。Qt/OpenCVの両方から到達する依存は共有区分へ一度だけ計上する。全区分の和は全ファイルサイズの和と一致する。同じ内容が複数の配布パスに存在する場合は実際に容量を占めるので控除しない。Python版の区分はパスによる推定であり、区分の厳密性と、ファイルサイズの実測値を区別する。

## 完了判定と結果

[ローカルでの実測比較](results/comparison.md) と [現行版の測定結果](results/legacy.md) を参照。NDIを除くC++構成は実ビルド・配布起動・ZIP展開後起動まで成功し、展開後107,654,765 bytes、ZIP 44,305,216 bytesだった。クリーンなGitHub ActionsとNDIを含む構成は未検証。

1. クリーンなWindows CIでmanifestの依存解決とReleaseビルドが成功する。
2. CTest、ライセンス/DLL検証、配布exe起動テストが成功する。
3. 展開後とZIPの実測値、同条件の現行版との比較を保存する。
4. NDIが未検証なら除外容量を明記し、全構成の検証は未完了とする。

最小アプリの数値は依存関係のベースラインであり、完全移植版の予測値ではない。未実装のアプリ本体の増分は未推定とする。
比較元のOpenCV Python wheelとC++ manifestではバージョン、動画バックエンド、同梱機能が異なるため、測定結果は配布構成全体の比較として扱う。
