# Windows CI実測結果（確認日：2026-10-23）

[PR #152](https://github.com/Nanahuse/DivergenceSplitter/pull/152) の [キャッシュなし実行 39777724343](https://github.com/Nanahuse/DivergenceSplitter/actions/runs/39777724343) は成功した。**NDIを含まない最小検証アプリの結果であり、NDIは未検証。完全移植版の容量は推定しない。** mainへのマージは行っていない。

## 検証結果と所要時間

- 固定vcpkg Manifestから38パッケージを導入し、C++23 Releaseビルドに成功。
- 検証ツールの16テスト、CTestの1テストに成功。
- CMake Install、Qt Deploy、依存DLL・ライセンス・開発用ファイル混入の検証に成功。
- 開発用PATHとQt/OpenCV用環境変数を除いた配布exeの起動に成功。
- **生成ZIPを別フォルダーに展開した後のexe起動にも成功。** Widgets、PNG、画像処理、PHash、MJPEG AVI、WebSocket/JSONを実行した。
- 同じcommitの既存CI（check / ui-integration）、Core distribution、Windows distributionも成功。

ジョブは2026-10-22 21:21:55〜23:55:32 JSTに実行された。以下は実測値。

| 項目 | 時間 |
| --- | ---: |
| ジョブ全体（セットアップ・Artifact保存・キャッシュ保存を含む） | 2時間33分37秒 |
| vcpkg呼び出し（ログの開始〜終了。取得・構築・導入を含む） | 2時間30分44.92秒 |
| configure（依存導入とCMakeチェックを含む） | 9,051.83秒 |
| アプリのReleaseビルド | 6.49秒 |
| CTest呼び出し | 1.28秒 |
| Install / Deploy | 6.64秒 |
| 配布検証・起動 | 0.90秒 |
| 集計・ZIP生成 | 2.85秒 |
| ZIP展開・起動 | 1.10秒 |
| 検証スクリプト全体 | 9,071.24秒 |

GitHub Actionsのbinary cacheはmiss、vcpkg復元数は**0**。既設のvcpkg binary cacheも使用しない設定で実行した。vcpkg自身の丸めた所要時間表示は `2.5 h`。主要portのログ表示はQt Base 54分、OpenCV 40分、protobuf 18分、ICU 9.7分だった。標準の `x64-windows` による依存のDebug/Release構築を含み、配布物にはDebugファイルを含めない。ローカルの初回依存導入56分より長いが、実行マシンが異なるため原因を特定した性能比較ではない。成功後にbinary cacheの保存も完了した。

## 配布容量

| 対象 | 展開後 bytes | 同一条件ZIP bytes |
| --- | ---: | ---: |
| 現行Python/Flet（NDIあり、CI再測定） | 336,741,879 | 120,071,454 |
| C++最小アプリ（NDIなし、ローカル） | 107,654,765 | 44,305,216 |
| C++最小アプリ（NDIなし、CI） | **107,651,764** | **44,304,402** |
| C++ CI − ローカル | −3,001 | −814 |

C++のCI配布物は142ファイル。展開後約107.65 MB（102.66 MiB）、ZIP約44.30 MB（42.25 MiB）。MBは1,000,000 bytes、MiBは1,048,576 bytes。現行版は [run 38922970221](https://github.com/Nanahuse/DivergenceSplitter/actions/runs/38922970221) の配布物を再測定したもので、ローカルの比較値と一致した。

両方のZIP条件はPython `3.14.6`、zlib `1.3.1.zlib-ng`、DEFLATE level 6、固定時刻、パス順、`distribution/` 接頭辞で一致する。異なるNDI有無・OpenCVバージョン・動画バックエンドを含む配布構成全体の比較であり、言語変更だけの効果や完全移植版の削減率とは扱わない。

| C++ CIの区分 | bytes |
| --- | ---: |
| 本体exe | 55,808 |
| Qt + 関連依存・プラグイン | 68,733,440 |
| OpenCV + 関連依存 | 10,112,000 |
| Qt/OpenCV共有依存 | 1,012,224 |
| Windows SDK描画ランタイム | 20,568,368 |
| MSVC Runtime | 1,646,032 |
| ライセンス・メタデータ | 5,522,739 |
| その他 | 1,153 |
| NDI | 未同梱・未測定 |

共有DLLは一度だけ計上し、区分の和は展開後サイズと一致する。上位ファイルは `icudt78.dll` 33,110,528 bytes、`dxcompiler.dll` 14,317,000 bytes、`Qt6Gui.dll` 6,998,016 bytes、`Qt6Widgets.dll` 6,158,336 bytes、`libcrypto-3-x64.dll` 5,358,080 bytes。全ファイルCSVはArtifact内の `cpp-report/files.csv`、上位20件は [CI要約JSON](cpp-ci-summary.json) に保存した。

## ローカルとの差と再現情報

ソースのhead commitは `3d1685a314eb39bea978716251ce5f29c46fd801`。ActionsがビルドしたPRのmerge commitは `c281ed6d03a89bb1581a3bc61e3a520e89ac8cbe`（製品mainへマージしたという意味ではない）。vcpkg baseline、Qt/OpenCVのバージョン、tripletはローカルと同じ。

| 項目 | ローカル | CI |
| --- | --- | --- |
| 環境 | Windows x64 / Visual Studio 2026 | Windows Server 2025 / `windows-2025-vs2026` |
| Runner image | — | `20261018.275.1` |
| MSVC compiler | `19.51.36252.0` | `19.51.36260.0` |
| MSVC tools | `14.51.36231` | `14.51.36231` |
| Windows SDK | `10.0.26100.0` | `10.0.26100.0` |
| CMake / Ninja | `4.3.1-msvc1` / `1.13.2` | 同じ |

容量差はOpenCVの `opencv_core4.dll` と `opencv_imgproc4.dll` が各−1,536 bytes、Qt関連の `qwindows.dll` が＋512 bytes、`harfbuzz.dll` が−512 bytes、文書・メタデータが合計＋71 bytes。Qt区分の合計差は0。文書3件のCRLF化が＋40 bytes、toolchain JSONの値の違いが＋31 bytesだった。コンパイラのパッチ版の違いもあり、DLLの差の原因を一つには断定しない。バイト単位の同一成果物は保証しない。

## Artifactと配布ZIPの区別

[測定Artifact](https://github.com/Nanahuse/DivergenceSplitter/actions/runs/39777724343/artifacts/12435661062) は **166,560,806 bytes**。外側はActions upload-artifactのlevel 0で、**C++ ZIPだけでなく、現行版ZIP・レポート・ログも含む転送用アーカイブ**。この値をC++配布ZIPの44,304,402 bytesと混同しない。[ビルド診断Artifact](https://github.com/Nanahuse/DivergenceSplitter/actions/runs/39777724343/artifacts/12434982458) は別途13,979,083 bytes。

- C++配布ZIP SHA256: `4ce426172dad90de95e1689189ec366a84054a8281a59c037beea29273f571c1`
- 外側Artifact SHA256: `8a40de93498020232894238363d1381bceb8cf0cffd9debc183caf66f7847e4e`

Artifactを取得し、外側のサイズ・SHA256がGitHub APIの記録と一致すること、内側C++ ZIPのサイズ・SHA256・全エントリーの展開後サイズ合計がレポートと一致することを確認した。`cpp-report/zip-verification.json` にCIでの展開後起動記録がある。

## 初回の失敗と残る項目

[最初の実行 39776874493](https://github.com/Nanahuse/DivergenceSplitter/actions/runs/39776874493) は、VS 2022限定の検出条件により依存導入前に失敗した。実際のWindows 2025イメージはVS 2026だったため、インストール済みMSVC x64ツールを選ぶよう修正し、上記のクリーンCI成功を確認した。初回失敗時のArtifactは現行版レポート等のみで、C++配布物ではない。

今回の範囲で残る実務上の課題は、キャッシュなし依存構築に約2.5時間かかることと、更新されるランナーのMSVC/SDKをメタデータで追跡する必要があること。容量最適化は追加していない。NDI公式SDK・DLLのコンパイル、動的ロード、初期化、特定SDKの取得・再配布経路は未検証のまま。MP4/H.264、実カメラ、NDI受信性能、完全なアプリ移植も検証対象外。

**NDIを除く今回のCI検証範囲は完了。マージはこの結果を確認した所有者が判断する。**
