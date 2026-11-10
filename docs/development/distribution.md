# Windows向け配布

[開発ガイド](README.md) · [ビルド環境](building.md) · [テスト](testing.md)

## ZIPの作成と検証

必要な環境を用意し、x64 Developer PowerShellでリポジトリのルートから実行します。

```powershell
cmake --preset full-release
cmake --build --preset full-release --parallel
ctest --preset full-release --output-on-failure
cmake --build build/full-release --target package
python tools/verify_windows_zip.py --build-dir build/full-release
```

配布ZIPは1種類だけです。NDI対応・非対応のビルドやZIPは作り分けません。NDI Runtimeは同梱せず、NDI入力を使用する利用者が別途インストールします。

CPackが作るファイル名は `DivergenceSplitter-<version>-windows-x64.zip` です。ZIP展開時は全体を囲むフォルダーがなく、実行ファイルなどが直接入っています。使うときは、ZIPの内容をすべて同じ場所へ展開してください。

GUI配布物には、`DivergenceSplitter.exe`、OpenCVなどのランタイムDLL、`LICENSE.txt`、`DISTRIBUTION-NOTICE.txt`、`licenses/`（`components.json`を含む）を含めます。Dear ImGuiは静的リンクするためDLLは不要です。QtのDLLやプラグイン、NDI Runtime DLL、NDI Runtimeのインストーラー、`vc_redist.x64.exe` は含めません。設定とサンプルは含めないため、対応するリポジトリのソースを取得してください。必要な環境では、Microsoft公式のVisual C++ Redistributableを別途インストールしてください。

検証スクリプトはZIPを展開し、必要な実行ファイルと通知を確認すること、Qtのランタイムが残っていないこと、NDI Runtime DLLやNDIのインストーラー、`vc_redist.x64.exe` が含まれていないこと、SDKの開発用ファイルが含まれていないことを調べます。その後、GUIの `--smoke-test` で、NDI Runtimeがない環境でも起動し、Aboutのライセンス表を描画できることを確認します。配布物に製品CLIは含めません。テスト実行ファイルとGUI起動試験はビルドディレクトリとCIで使用します。

## CI workflow

[C++23](../../.github/workflows/cpp23.yml)は、PR、`main` へのpush、手動実行で動きます。Windows、MSVC、Ninja、vcpkgを使い、`ci` プリセットで1種類だけビルドします。Dear ImGui（v1.91.9b）とImPlot（v0.17）はconfigure時にFetchContentで取得します。Qtのインストール手順はありません。

固定リビジョンのBridge TestHostもビルドし、CTest、実TestHostとの結合テスト、ZIPの作成、展開後の起動検証まで実行します。

- ビルドにNDI SDKは不要です。NDIヘッダーはリポジトリに固定版を同梱しています。
- NDI Runtimeの初期化・受信テストは、リポジトリSecret `NDI_SDK_URL_WINDOWS` がある場合だけ実行します。CIは公式SDKを取得し、`NDI_RUNTIME_DIR_V6` をSDK内のRuntimeフォルダーへ向けてループバックテストを実行します。
- forkのPRやSecretがない実行では、NDI Runtimeテストをスキップします。ビルド・起動・Camera・Videoのテストは常に実行します。
- Secretがない場合もNDI ON/OFFビルドへ切り替えず、同じ1種類のビルドを続行します。
- 成果物 `DivergenceSplitter-cpp23-windows-x64` は1種類だけアップロードし、CTest結果もアップロードします。

## 第三者ライセンスの通知

アプリのソースは[MIT](../../LICENSE)です。[DISTRIBUTION-NOTICE.txt](../../DISTRIBUTION-NOTICE.txt) にDear ImGui、ImPlot、OpenCV、Boost、rapidyaml（ryml）、c4core、nlohmann/json、Bridgeクライアント、カメラ列挙の移植部分などを記載します。それぞれ別のライセンスが適用されます。

[licenses/components.json](../../licenses/components.json)をコンポーネントとライセンスの正本とし、About画面、収集スクリプト、ZIP検証で共有します。install・package時には[collect_licenses.py](../../tools/collect_licenses.py)が、この一覧に従ってvcpkgパッケージの通知、取得したBridgeのライセンス、FetchContentで取得したDear ImGuiの `LICENSE.txt` とImPlotの `LICENSE`、同梱するNDIヘッダーの通知を集めます。カメラ列挙部分の許諾ライセンスは、[third-party-license-lock.json](../../tools/third-party-license-lock.json)に記録した固定コミットから取得します。取得した本文は、Git管理外のビルドキャッシュに保存します。

必要な通知がない場合、取得した本文が固定内容と違う場合、パッケージ化に失敗します。rymlとc4coreの通知は、`licenses/ryml.txt` と `licenses/c4core.txt` として必ず含め、ZIP検証でも確認します。他のライブラリが依存するライブラリの通知も、`licenses/vcpkg/` に含めます。

ライセンス本文を短い説明や要約へ置き換えないでください。依存ライブラリを更新したときは、ビルド結果に加えて、ZIP内の通知も確認します。そのZIPの利用条件は、同梱されたライセンスファイルで確認できるようにします。

## 配布ZIP容量の比較

比較条件を揃えて測定しました。Qt Widgets版は同じリポジトリの `2920fb6` を同じMSVC・vcpkg（OpenCV 4.14）・Release・DEFLATE level 6でビルドし、`windeployqt` でQtランタイムとプラグインを配置したZIPです。Dear ImGui版は今回のブランチのReleaseビルドです。どちらもNDI Runtimeと `vc_redist.x64.exe` を含みません。

| 構成 | 圧縮後ZIP | 比較 |
| --- | ---: | --- |
| Qt Widgets (`2920fb6`) | 40,538,833 bytes | 基準 |
| Dear ImGui (今回、比較用にlevel 6で再圧縮) | 5,903,447 bytes | 約85.4%削減 |

配布ZIPは1種類で、NDI Runtimeの有無による差はありません。今回のローカル実測は5,723,621 bytes（NDI Runtimeと `vc_redist.x64.exe` を含まない単一ZIP）です。

## NDI Runtimeの扱い

NDI®はVizrt NDI ABの登録商標です。NDI公式サイトは https://ndi.video/ です。配布ZIPには `Processing.NDI.Lib.x64.dll`、`Processing.NDI.Lib.Licenses.txt`、NDI Runtimeのインストーラーを含めません。

NDI入力を使用する利用者は、NDI公式サイトからNDI Runtimeを別途インストールします。アプリは起動時にインストール済みRuntimeを検出し、見つからない場合はNDI入力だけを無効にします。Runtimeのライセンス条件と第三者の通知は、インストールしたRuntimeに含まれるものを確認してください。

`licenses/NDI-TERMS.txt` は、NDI Runtimeを別途利用する場合に適用される条件の説明として同梱します。SDK契約書PDF、SDKヘッダー、インポートライブラリ、インストーラー、送信サンプル、NDI ToolsはZIPに含めません。検証スクリプトは、これらの開発用ファイルやNDI Runtimeが含まれているとエラーにします。

ランタイムの個別条件と公式のライセンス・配布規定へのリンクは [licenses/NDI.md](../../licenses/NDI.md) を参照してください。NDI対応を理由に別のZIPを作らず、単一の配布物で商標表記、公式サイトへのリンク、利用条件を保ちます。固定SDKを更新する前に、実際の契約書、最新のSDKの要件を含む再配布条件を確認してください。
