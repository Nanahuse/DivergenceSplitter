# Windows向け配布

[日本語（正本）](distribution.md) | [English](distribution.en.md)

[開発ガイド](README.md) · [ビルド環境](building.md) · [テスト](testing.md)

## ZIPの作成と検証

必要な環境を用意し、x64 Developer PowerShellで `cpp/` から実行します。

```powershell
cmake --preset full-release
cmake --build --preset full-release --parallel
ctest --preset full-release --output-on-failure
cmake --build build/full-release --target package
python tools/verify_windows_zip.py --build-dir build/full-release --ndi OFF
```

この既定の開発ビルドはNDI無効です。NDIを同梱する場合は[NDIのオプション](building.md#ndi対応ビルド)で設定し、同じプリセットでビルド・テスト・パッケージ化して、検証時に `--ndi ON` を渡します。SDKや依存構成を切り替える場合は別ディレクトリを使ってください。検証対象ディレクトリのZIPは1つである必要があります。

CPackは `DivergenceSplitter-<version>-windows-x64.zip` を作成し、外側のトップレベルディレクトリは付けません。全体を展開して使ってください。GUI配布物には `DivergenceSplitter.exe`、`divergencesplitter-cli.exe`、ランタイムDLL、Qtプラグイン、`LICENSE.txt`、`DISTRIBUTION-NOTICE.txt`、`licenses/` を含みます。現行のinstall設定は文書・サンプルを同梱しないため、対応するソースのリビジョンから取得します。

検証ヘルパーはZIPを展開し、実行ファイル・通知・SDK除外、CLIの `--help`、GUIの `--smoke-test` を確認します。Qt／NDIの探索用環境変数を外し、PATHをZIPとWindowsのシステムディレクトリに限定して起動します。ONではランタイム・通知の固定ハッシュと、`--ndi-check` によるローカルDLLの初期化も確認します。起動確認は実入力の受信確認とは別です。

## CI workflow

[C++23](../../../.github/workflows/cpp23.yml) はPR、`main` へのpush、手動実行で動きます。Windows、MSVC、Ninja、vcpkg、外部Qt 6.8.3、`ci` プリセットを使います。固定Bridge TestHostをビルドし、CTestと実TestHost結合、ZIP作成、展開後の検証を行います。

- forkのPRはNDI OFFだけをビルドし、SDKのSecretは渡しません。
- 同じリポジトリのPR、mainへのpush、手動実行はOFFとONの両方が必須です。SDKを取得できなくてもOFFへ黙って切り替えません。
- ONには公式Windows SDKのURLを持つリポジトリSecret `NDI_SDK_URL_WINDOWS` が必要です。[get_ndi_sdk.py](../../tools/get_ndi_sdk.py) が `curl.exe` で取得し、インストーラーのSHA-256、バージョン、Authenticode発行者、展開したヘッダー・ランタイム・通知・契約書を検証します。`NDI_SDK_DIR` をジョブ環境へ書き込みます。HTTPエラーやタイムアウトでは失敗して部分ファイルを消し、URLと捕捉したcurl出力はログに出しません。
- [ndi-sdk-lock.json](../../tools/ndi-sdk-lock.json) はSDK 6.3.2.0とinnoextract 1.9の確認済みハッシュを保持します。SDKを公開Actionsキャッシュへ保存しません。vcpkgのキャッシュは依存ダウンロード・バイナリだけです。
- ONだけが `DivergenceSplitter-cpp23-windows-x64` をアップロードし、両構成がJUnit形式のCTest結果をアップロードします。一時作業ブランチへのpushは起動条件ではありません。PRまたは手動実行で検証します。

## 第三者ライセンスの通知

アプリのソースは[MIT](../../LICENSE)です。[DISTRIBUTION-NOTICE.txt](../../DISTRIBUTION-NOTICE.txt) にQt、OpenCV、Boost、yaml-cpp、nlohmann/json、Bridgeクライアント、カメラ列挙の移植部分などを記載します。それぞれ別のライセンスが適用されます。

install・package時に [collect_licenses.py](../../tools/collect_licenses.py) が実際にインストールしたvcpkgの通知と、取得したBridgeのライセンスを集めます。カメラ列挙の元ライセンスと外部Qt 6.8.3の本文も、[third-party-license-lock.json](../../tools/third-party-license-lock.json) にある固定コミットから取得します。取得した本文はGit管理外のビルドキャッシュに保存します。通知の不足、対応しない外部Qtバージョン、固定内容の変化ではパッケージ化を失敗させます。推移的な依存の通知は `licenses/vcpkg/` に含めます。

ライセンス本文を短い要約で置き換えないでください。依存を更新するときはビルドだけでなく、パッケージ内の通知も確認します。そのZIPに適用する通知は配布物内のライセンスファイルです。

## NDIランタイムの同梱物

NDI®はVizrt NDI ABの登録商標です。[NDI公式サイト](https://ndi.video/)。ONのZIPには `Processing.NDI.Lib.x64.dll`、変更しない `Processing.NDI.Lib.Licenses.txt`、アプリ側で管理する [licenses/NDI-TERMS.txt](../../licenses/NDI-TERMS.txt) も含みます。

SDK契約書PDFは取得・configureで検査しますが同梱しません。ヘッダー、インポートライブラリ、インストーラー、送信サンプル、NDI Toolsも除外し、検証ヘルパーが開発用ファイルの混入を拒否します。OFFには説明用の通知だけを含み、NDI DLLは含みません。

ランタイムの個別条件と公式のライセンス・配布規定へのリンクは [licenses/NDI.md](../../licenses/NDI.md) を参照してください。NDI対応パッケージには商標表記、公式サイトへのリンク、ランタイム通知、利用条件を保ちます。固定SDKを更新して別のZIPを公開する前に、実際の契約書、最新版SDKの要件を含む再配布要件を確認してください。
