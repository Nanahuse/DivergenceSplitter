# Windows向け配布

[開発ガイド](README.md) · [ビルド環境](building.md) · [テスト](testing.md)

## ZIPの作成と検証

必要な環境を用意し、x64 Developer PowerShellでリポジトリのルートから実行します。

```powershell
cmake --preset full-release
cmake --build --preset full-release --parallel
ctest --preset full-release --output-on-failure
cmake --build build/full-release --target package
python tools/verify_windows_zip.py --build-dir build/full-release --ndi OFF
```

このコマンド例はNDI無効の開発用ZIPを作ります。NDIを同梱する場合は、[NDIのオプション](building.md#ndi対応ビルド)を有効にし、同じプリセットでビルド・テスト・パッケージ化してください。検証時には `--ndi ON` を渡します。

SDKや依存ライブラリの構成を変えるときは、別のビルドディレクトリを使ってください。検証スクリプトに指定するディレクトリには、検証対象のZIPを1つだけ置いてください。

CIはパッケージ化の前にMicrosoft公式の c_redist.x64.exe をビルドディレクトリへダウンロードします。ローカルで同じZIPを作る場合も、uild/<preset>/vc_redist.x64.exe を用意してください。

CPackが作るファイル名は `DivergenceSplitter-<version>-windows-x64.zip` です。ZIP展開時は全体を囲むフォルダーがなく、実行ファイルなどが直接入っています。使うときは、ZIPの内容をすべて同じ場所へ展開してください。

GUI配布物には、`DivergenceSplitter.exe`、`divergencesplitter-cli.exe`、OpenCVなどのランタイムDLL、`vc_redist.x64.exe`（存在する場合）、`LICENSE.txt`、`DISTRIBUTION-NOTICE.txt`、`licenses/` を含めます。Dear ImGuiは静的リンクするためDLLは不要です。QtのDLLやプラグインは含めません。文書とサンプルは含めないため、対応するリビジョンのソースから取得してください。

検証スクリプトはZIPを展開し、必要な実行ファイルと通知があること、Qtのランタイムが残っていないこと、SDKの開発用ファイルが混ざっていないことを調べます。その後、CLIの `--help` とGUIの `--smoke-test` で起動を確認します。

起動時はNDIの探索用環境変数を外し、PATHを展開先とWindowsのシステムディレクトリだけにします。NDI有効の場合、ランタイムと通知の固定ハッシュ、および `--ndi-check` による展開先DLLの初期化も確認します。この起動試験だけで、実際の入力を受信できたことにはなりません。

## CI workflow

[C++23](../../.github/workflows/cpp23.yml)は、PR、`main` へのpush、手動実行で動きます。Windows、MSVC、Ninja、vcpkgを使い、`ci` プリセットでビルドします。Dear ImGuiはconfigure時にFetchContentで取得します。Qtのインストール手順はありません。

固定リビジョンのBridge TestHostもビルドし、CTest、実TestHostとの結合テスト、ZIPの作成、展開後の起動検証まで実行します。

- forkのPRはNDI OFFだけをビルドし、SDKのSecretは渡しません。
- 同じリポジトリのPR、mainへのpush、手動実行はOFFとONの両方が必須です。SDKの取得に失敗した場合も、OFFへ切り替えて続行しません。
- ONには公式Windows SDKのURLを持つリポジトリSecret `NDI_SDK_URL_WINDOWS` が必要です。[get_ndi_sdk.py](../../tools/get_ndi_sdk.py) が `curl.exe` で取得し、インストーラーのSHA-256、バージョン、Authenticode発行者、展開したヘッダー・ランタイム・通知・契約書を検証します。`NDI_SDK_DIR` をジョブ環境へ書き込みます。HTTPエラーやタイムアウトでは失敗して部分ファイルを消し、URLと捕捉したcurl出力をログに出しません。
- [ndi-sdk-lock.json](../../tools/ndi-sdk-lock.json) はSDK 6.3.2.0とinnoextract 1.9の確認済みハッシュを保持します。SDKを展開Actionsキャッシュへ保存しません。vcpkgのキャッシュは依存ダウンロードとバイナリだけです。
- ONだけが `DivergenceSplitter-cpp23-windows-x64` をアップロードし、両構成がJUnit形式のCTest結果をアップロードします。一時作業ブランチへのpushは起動条件ではありません。PRまたは手動実行で検証します。

## 第三者ライセンスの通知

アプリのソースは[MIT](../../LICENSE)です。[DISTRIBUTION-NOTICE.txt](../../DISTRIBUTION-NOTICE.txt) にDear ImGui、OpenCV、Boost、rapidyaml（ryml）、c4core、nlohmann/json、Bridgeクライアント、カメラ列挙の移植部分などを記載します。それぞれ別のライセンスが適用されます。

install・package時には[collect_licenses.py](../../tools/collect_licenses.py)が、使用したvcpkgパッケージの通知、取得したBridgeのライセンス、FetchContentで取得したDear ImGuiの `LICENSE.txt` を集めます。カメラ列挙部分の許諾ライセンスは、[third-party-license-lock.json](../../tools/third-party-license-lock.json)に記録した固定コミットから取得します。取得した本文は、Git管理外のビルドキャッシュに保存します。

必要な通知がない場合、取得した本文が固定内容と違う場合、パッケージ化に失敗します。rymlとc4coreの通知は、`licenses/ryml.txt` と `licenses/c4core.txt` として必ず含め、ZIP検証でも確認します。他のライブラリが依存するライブラリの通知も、`licenses/vcpkg/` に含めます。

ライセンス本文を短い説明や要約へ置き換えないでください。依存ライブラリを更新したときは、ビルド結果に加えて、ZIP内の通知も確認します。そのZIPの利用条件は、同梱されたライセンスファイルで確認できるようにします。

## 配布ZIP容量の比較

比較条件を揃えて測定しました。Qt Widgets版は同じリポジトリの `2920fb6` を同じMSVC・vcpkg（OpenCV 4.14）・Release・NDI OFF・DEFLATE level 6でビルドし、`windeployqt` でQtランタイムとプラグインを配置したZIPです。Dear ImGui版は今回のブランチのReleaseビルドです。vc_redistの有無は、生成したZIPから `vc_redist.x64.exe` だけを除いて同じ条件で再圧縮して比較しました。

| 構成 | NDI | vc_redist | 圧縮後ZIP | 比較 |
| --- | --- | --- | ---: | --- |
| Qt Widgets (`2920fb6`) | OFF | なし | 40,538,833 bytes | 基準 |
| Dear ImGui (今回) | OFF | なし | 6,571,420 bytes | 約83.8%削減 |
| Qt Widgets (`2920fb6`) | OFF | あり | 57,603,103 bytes | 基準 |
| Dear ImGui (今回) | OFF | あり | 31,760,842 bytes | 約44.9%削減 |
| Dear ImGui (今回) | ON | あり | 35,302,635 bytes | NDI ONの実配布ZIP |

CI実測はNDI OFF 31,630,340 bytes、NDI ON 35,302,635 bytesです。Qt版のNDI ONはこの環境にSDKがないため未測定で、上記の削減率はNDI OFF同士の比較です。`vc_redist.x64.exe` を同梱する判断は維持し、比較では両方の有無を揃えています。

## NDIランタイムの同梱物

NDI®はVizrt NDI ABの登録商標です。NDI公式サイトは https://ndi.video/ です。ONのZIPには `Processing.NDI.Lib.x64.dll`、変更しない `Processing.NDI.Lib.Licenses.txt`、アプリ側で管理する[licenses/NDI-TERMS.txt](../../licenses/NDI-TERMS.txt) も含みます。

SDK契約書PDFはSDKの取得時とconfigure時に検査しますが、ZIPには入れません。ヘッダー、インポートライブラリ、インストーラー、送信サンプル、NDI Toolsも同梱しません。検証スクリプトは、これらの開発用ファイルがあるとエラーにします。

NDI無効のZIPにも説明用の通知は含めますが、NDI DLLは含めません。

ランタイムの個別条件と公式のライセンス・配布規定へのリンクは [licenses/NDI.md](../../licenses/NDI.md) を参照してください。NDI対応パッケージには商標表記、公式サイトへのリンク、ランタイム通知、利用条件を保ちます。固定SDKを更新して別のZIPを展開する前に、実際の契約書、最新のSDKの要件を含む再配布条件を確認してください。
