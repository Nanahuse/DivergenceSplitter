# ローカル実測結果（2026-10-22）

標準のvcpkg構成でQt 6 Widgets・OpenCV Contribを使用するC++23最小アプリを実ビルドし、配布フォルダーとZIPを測定した。**C++側はNDIを含まない。完全移植版の容量や、その削減率を示す結果ではない。クリーンなGitHub Actionsでの実行は未実施。**

## 同じZIP条件での比較

| 対象 | 展開後 bytes | 展開後 MiB | ZIP bytes | ZIP MiB |
| --- | ---: | ---: | ---: | ---: |
| 現行Python/Flet配布物（NDIを含む） | 336,741,879 | 321.14 | 120,071,454 | 114.51 |
| C++23最小アプリ（NDIを含まない） | 107,654,765 | 102.67 | 44,305,216 | 42.25 |

比較元は [mainのrun 38922970221](https://github.com/Nanahuse/DivergenceSplitter/actions/runs/38922970221)。取得した元Artifactは119,173,986 bytesだが、上の比較には同じスクリプトで再圧縮した120,071,454 bytesを使用した。

ZIP条件は両方ともPython 3.14.6、zlib `1.3.1.zlib-ng`、DEFLATE level 6、固定時刻、パス順、同じ `distribution/` 接頭辞。ZIPやレポートを配布フォルダー内へ混入させていない。MBは1,000,000 bytes、MiBは1,048,576 bytes。

## C++配布物の内訳

| 区分 | bytes | MiB |
| --- | ---: | ---: |
| 本体exe | 55,808 | 0.05 |
| Qt + 関連依存・プラグイン | 68,733,440 | 65.55 |
| OpenCV + 関連依存 | 10,115,072 | 9.65 |
| Qt/OpenCV共有依存 | 1,012,224 | 0.97 |
| Windows SDK描画ランタイム（Qt Deploy標準収集） | 20,568,368 | 19.62 |
| MSVC Runtime | 1,646,032 | 1.57 |
| ライセンス・ビルド情報・テスト記録 | 5,522,668 | 5.27 |
| その他（プロジェクトLICENSE、qt.conf） | 1,153 | 0.00 |
| NDI | 未測定・未同梱 | — |

合計142ファイル。各ファイルを一度だけ計上し、全区分の和と展開後容量が一致することを確認した。共有DLLをQtとOpenCVの両方へ加算していない。vcpkgの標準default-featuresを使って依存をビルドし、アプリから必要なDLLは依存スキャンで収集した。独自のOpenCV最小ビルドやtripletは使っていない。

Qt Deployが収集した `d3dcompiler_47.dll`、`dxcompiler.dll`、`dxil.dll` はWindows SDKのx64再配布ファイルとSHA256が一致し、同じSDKのライセンス・第三者通知を収集できた。ライセンス類には、保守性を優先して全導入portの文書とビルド情報も含めている。

## 検証した内容

- MSVCによるC++23 Releaseビルド成功。
- CTest成功：実ウィンドウ、PNG読込、画像処理、PHash、3フレームのMJPEG AVI読込、WebSocket/JSONの往復。
- CMake Install + Qt Deploy + 依存DLL収集成功。
- DLL所有者、MSVC Runtime、ライセンス・SDK再配布ファイルの確認成功。PDB、ヘッダー、静的ライブラリ、Debugディレクトリーを含まないことを確認。
- 新規配布フォルダーから、開発環境のPATHとQt/OpenCVの環境設定を除いたexe起動に成功。
- **生成ZIPを別フォルダーへ展開した後のexe起動にも成功。**
- 容量・配布検証ツールの16テスト、Ruff、tyに成功。

ビルドフォルダーでのCTestは、vcpkgのQtプラグインパスを明示している。配布物のテストはこの環境設定を削除し、Qt Deployの `qt.conf` を使う。初回はビルド用プラグインパスの不足によるタイムアウト、SDK由来DLLの未分類、Windows環境変数名の扱いによる例外を検出して修正し、最終的に一連の手順を新規配布フォルダーで再実行した。

## 環境と再現用データ

- ソース：ローカル作業ツリー（基点commit `b941b32847f01c4f80e54c46c3c27926f925edce`）。GitHubへ未push。
- MSVC compiler `19.51.36252.0`、toolset `14.51.36231`（Visual Studio 2026）。
- Windows SDK `10.0.26100.0`、CMake `4.3.1-msvc1`、Ninja `1.13.2`。
- vcpkg `9e593bb18ea69cc5095e012465dcd675a822ed0d`、Qt Base `6.11.1#1`、Qt WebSockets `6.11.1`、OpenCV `4.12.0#7`、`x64-windows`。
- vcpkgログ上の初回38依存インストールは56分。うちOpenCVは12分、Qt Baseは16分。Debug/Release両方を含むローカルの実測であり、CI時間の見積もりではない。
- C++ ZIP SHA256：`7f279f743c6da9aac650f26e463a98e1af364239aed67f91bdcd561b37684f82`。

[現行版の詳細](legacy.md)、[C++要約JSON](cpp-local-summary.json)、[C++全ファイルCSV](cpp-local-files.csv) を保存した。完全なJSON、ZIP、比較結果はローカルの `build/size-probe/{legacy,cpp}-report/` にある。CI実行時は同じ形式をArtifactへ保存する。

## 未検証・未推定の項目

NDI公式SDKが未提供のため、公式ヘッダーを使うコードのコンパイル、DLL初期化、特定SDKの取得・配布経路を実証できていない。NDI対応コード・同梱処理は用意したが、今回の107,654,765 bytesへNDIの容量を含めてはいない。現行版のNDI DLLは29,863,120 bytesだったが、異なるSDKのC++配布容量へは転記しない。

また、現行版はopencv-contrib-python `5.0.0.93`、C++側はOpenCV `4.12.0#7` で、動画バックエンドや同梱機能も異なる。C++側には完全なGUI、Scenario Runtime、Detector、設定処理、製品アセットを実装していない。これらの増分は未推定。

今回の実測は「標準構成のQt/OpenCVを使う最小アプリ」の容量基準として利用できる。全構成の完了判定には、用意した `windows-2025` CIでの実行と、公式NDI SDKを指定した検証が残る。ローカルのVisual Studio 2026と、CIで選択するVisual Studio 2022の差も、CI実測後に確認する。
