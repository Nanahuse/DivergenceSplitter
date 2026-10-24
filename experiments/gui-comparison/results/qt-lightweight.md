# Qt Widgetsの軽量化検証（A / B / C）

同じGUI試作で、標準Qtを残してFeature削減と配布最適化を比較した。**A/B/Cとwx・ImGuiの5構成すべてがクリーンWindows CIでビルド・配布試験に成功した。** 容量は実測値で、完全移植版の推定ではない。NDIと実Scenario Runtimeは全構成に含まない。GUIライブラリの採用・mainへのマージは行っていない。

## 共通条件と構成

- PR #153の既存 `experiment/gui-library-comparison` ブランチ。実装追加は `404aafc`。GUI試作本体・共通mock・wx/ImGuiのfeatureを変更せず、Qt用の独立したテストexeを追加した。
- Windows x64、MSVC、C++23、Release、CMake/Ninja、vcpkg baseline `9e593bb18ea69cc5095e012465dcd675a822ed0d`。Qt `6.11.1#1`、OpenCV `4.12.0#7[contrib]`とそのdefault featuresを維持する。
- ZIPは従来と同じDEFLATE level 6、正規化した順序・時刻・格納パス。MB=1,000,000 bytes。テストexe・ログ・画面保存は測定ZIPに含めない。
- build・vcpkg install・配布・レポートをそれぞれ `qt` / `qt-features` / `qt-optimized` に分ける。旧配布先は上書きせず、既存のQt・wx・ImGui配布ファイルはSHA256が前回記録と一致することを確認した。

| 構成 | vcpkg feature | 配布方法 |
| --- | --- | --- |
| A 標準Qt | 既存 `qt`。default featuresを維持 | 既存のQt DeployとDLL収集 |
| B Feature削減 | `qt-lean`。`default-features: false`＋必要なfeatureを明示 | Aと同じQt DeployとDLL収集 |
| C Feature削減＋配布最適化 | Bと同じ `qt-lean` | 公式の除外オプション＋同じDLL収集 |

B/CはWidgets・Gui・thread、FreeType/HarfBuzz、PNG/JPEG、Network/DNS、OpenGL、sessionmanager、doubleconversion/pcre2、windeployqtを要求する。ICU・OpenSSL・SQL、未使用のDBus・async/concurrent/testlib・Qt側のbrotli/zstd等を要求しない。ただし、FreeTypeの推移依存のbrotliなど、他の依存が必要とするものは残る。不要な依存を取り除くために独自port・overlay・tripletやQtへの追加patchは作っていない。

外部ICU featureはOFFだが、ローカルの生成済みQt設定は `QT_FEATURE_winsdkicu=1`。**WindowsのICU APIまで使わない構成ではない。** SQL featureはAでON、B/CでOFFだが、元のAもQt6Sql.dllを配布しておらず、SQL DLLの削減量を架空に計上しない。

Cの追加オプションは `--no-system-d3d-compiler --no-system-dxc-compiler --network --skip-plugin-types generic,styles`。この試作はFusion/raster Widgetsを明示し、TUIO入力と外部native style pluginを使わない。NetworkはTUIOの推移依存に頼らず明示して残し、platforms・imageformats・networkinformation・tlsを維持する。依存収集処理は従来のまま実行し、除外したDLLやpluginが復活したらpackagerが失敗する。配布後にDLLを削除する処理はない。

| 配布・featureの確認 | A | B | C |
| --- | --- | --- | --- |
| vcpkg ICU DLL | 3 DLL同梱 | 同梱なし | 同梱なし |
| OpenSSL crypto DLL | 同梱 | 同梱なし | 同梱なし |
| Qt SQL feature | ON（SQL DLL自体は未同梱） | OFF | OFF |
| SDK D3D/DXC compiler DLL | 3 DLL同梱 | 3 DLL同梱 | 同梱なし |
| TUIO / native style plugin | 同梱 | 同梱 | 除外 |
| Windows platform / imageformats / Network / TLS | 維持 | 維持 | 維持 |

## クリーンWindows CIでの容量

[測定run 40064070079](https://github.com/Nanahuse/DivergenceSplitter/actions/runs/40064070079)、head source `404aafc`。同じrunの3構成を比較する。元の基準Aはrun `39964806286`の展開後107,448,895 / ZIP 44,254,925 bytesとして[旧記録](ci-distribution.json)に保持する。今回Aの展開後が465 bytes増えた分は、同梱する `build-metadata/vcpkg.json` の新feature記述で、ファイル構成は同じである。ZIPは180 bytes増え、2桁表示の丸め境界を跨ぐため44.26MBとなる。

| 構成 | 展開後 bytes | 配布ZIP bytes | ZIP MB | 外側Artifact bytes |
| --- | ---: | ---: | ---: | ---: |
| A 標準 | 107,449,360 | 44,255,105 | 44.26 | 44,642,451 |
| B Feature削減 | 66,287,104 | 27,336,755 | 27.34 | 27,712,411 |
| C 配布最適化 | 45,201,548 | 17,553,391 | 17.55 | 17,913,437 |

外側Actions Artifactは `compression-level: 0` で、内側配布ZIPにログ・JSON・CSV・試験画面等を加えた運搬用アーカイブ。内側ZIPの圧縮率や配布容量と混同しない。

A→CのZIP削減は **26,701,714 bytes（60.34%）**。B/Cにvcpkg ICU・OpenSSL crypto・SQLのDLLはなく、Cにはd3dcompiler_47 / dxcompiler / dxilとgeneric・styles pluginがない。

| 構成 | 復元package数 | Qt初回ビルド（vcpkgログ） | configure＋依存解決 | ジョブ全体 |
| --- | ---: | --- | ---: | ---: |
| A | 37 | cache復元（ビルドなし） | 0分57秒 | 3分45秒 |
| B | 27 | 32 min | 33分09秒 | 35分54秒 |
| C | 27 | 48 min | 49分31秒 | 53分00秒 |

B/Cは同じQt featureを別runnerで初回ビルドした記録で、所要時間差を配布オプションのビルド性能差とは解釈しない。両者の共通ファイルのサイズは一致するが、独立ビルドしたQt DLL等のSHA256は一致しない。原因内訳は未解析で、完全なbyte再現性の実証とはしない。配布オプションだけの差分は、同じDLL cacheを使ったローカルB/Cで確認した。

各Artifactの正確なbytes・ID、ジョブ時刻、toolchain/checkout情報と検証内容は[実測メタデータ](qt-lightweight/context.json)。個別のファイル一覧・SHA256・ZIP条件は[保存したCI report JSON](qt-lightweight/)から再確認できる。GitHubのcache-hitは完全一致キーの判定であり、falseでもprefixから依存を復元している。Qt Featureの初回ビルドを、全依存がキャッシュなしのビルドと呼ばない。

## ローカルの容量と差分

| 構成 | 展開後 bytes | ZIP bytes | 展開後 MB | ZIP MB |
| --- | ---: | ---: | ---: | ---: |
| A 既存標準Qt | 107,513,348 | 44,273,201 | 107.51 | 44.27 |
| B Feature削減 | 66,352,057 | 27,361,572 | 66.35 | 27.36 |
| C 配布最適化 | 45,204,525 | 17,560,717 | 45.20 | 17.56 |

既存のAをそのまま使用し、同じ圧縮条件で比較した。B/CのOpenCV 5 DLLはAとSHA256が一致する。B→CではQt本体を含む共通DLLのSHA256も一致し、依存featureの再変更はない。

ローカルのA→Bで取り除かれた主なDLLは `icudt78.dll` 33,110,528、`icuin78.dll` 2,807,296、`icuuc78.dll` 1,845,248、`libcrypto-3-x64.dll` 5,358,080、`zstd.dll` 657,920 bytes。反対にQt6Core.dllは5,313,024→9,153,536 bytesへ増えた。複数featureを同時に変更しており、この増加の原因内訳は未解析。除外DLLのサイズの単純合計を、配布物全体の削減量とは扱わない。

ローカルB→Cでは次の8ファイルがなくなり、展開後は21,147,532 bytes減った。残すファイルを手動選別・削除した結果ではなく、deployオプションと既存の通知収集ルールによる差分である。

| ファイル | bytes |
| --- | ---: |
| dxcompiler.dll | 14,317,000 |
| d3dcompiler_47.dll | 4,741,568 |
| dxil.dll | 1,509,800 |
| qmodernwindowsstyle.dll | 225,792 |
| qtuiotouchplugin.dll | 81,920 |
| SDK license / third-party notices | 270,852 |
| SDK graphics metadata | 600 |

| 構成 | CI − local 展開後 bytes | CI − local ZIP bytes |
| --- | ---: | ---: |
| A | -63,988 | -18,096 |
| B | -64,953 | -24,817 |
| C | -2,977 | -7,326 |

A/Bの差は主にSDK graphics DLL（計61,976 bytesの差）。Cはこれらを含まないため、差が2,977 bytesに縮まる。OpenCV・一部共通DLLと改行/metadataにも差がある。SDK DLLの出所と通知はそれぞれ検証済み。ファイル別の差分はcontext.jsonに保存し、環境間のバイト一致とはしない。

ローカルは新featureのQtを初回にビルドし、他27 packageをcacheから復元した。vcpkgの表示は全体約16分。Bのhelper実行約58秒はこの先行依存ビルドを含まない。CはBと同じfeatureのbinary cacheを使い、別install先へ展開した約73秒のhelper実行。CI初回の所要時間とは別記録にする。

## 動作検証

| 確認 | A | B | C |
| --- | --- | --- | --- |
| CTest 6件（共通mock、小規模/大量GUI契約、画面保存、長押し中の終了） | CI成功 | local / CI成功 | local / CI成功 |
| 配布フォルダーsmall / ZIP展開先largeのGUI契約（各13チェック） | CI成功 | local / CI成功 | local / CI成功 |
| 日本語glyph / fallback、画面保存 | local / CI成功 | local / CI成功 | local / CI成功 |
| IME preedit / commitイベント、Unicode JSON | local / CI成功 | local / CI成功 | local / CI成功 |
| 実IMEの変換候補・確定を物理操作 | 未検証 | 未検証 | 未検証 |
| platform・JPEG・Schannel plugin、PNG/JPEG encode/decode | local / CI成功 | local / CI成功 | local / CI成功 |
| loopback TCP、日本語payload、localhost解決 | local / CI成功 | local / CI成功 | local / CI成功 |
| Fusion paletteの明暗切替・復元 | local / CI成功 | local / CI成功 | local / CI成功 |
| ICU/crypto/SQL DLLが再収集されない | 対象外 | local / CI成功 | local / CI成功 |
| SDK graphics DLL / generic・styles pluginが再収集されない | 対象外 | 対象外 | local / CI成功 |

追加の独立テストはinstall先とZIP展開先に対して各19種類のチェック。テストexeだけを別フォルダーへコピーし、PATHから開発環境を除き、Qt plugin pathは配布先を明示し、Qtが追加するテストexe専用folderにはDLL/pluginを置かない。Qt Core/Gui/Widgets/Networkとqwindowsの実ロード元が配布先内であることを検証する。native platform、画像・TLSのplugin診断ログもArtifactに保存する。日本語のfontはローカルがYu Gothic UI、今回CIのAはMS UI Gothicで、OSのfontを使い、fontを新規同梱していない。

ローカル画面：[A](qt-lightweight/captures/local-qt-japanese.png) / [B](qt-lightweight/captures/local-qt-features-japanese.png) / [C](qt-lightweight/captures/local-qt-optimized-japanese.png)。CI画面：[A](qt-lightweight/captures/ci-qt-japanese.png) / [B](qt-lightweight/captures/ci-qt-features-japanese.png) / [C](qt-lightweight/captures/ci-qt-optimized-japanese.png)。

IMEイベント自動試験はOSの変換候補UIや実キーボードによる変換を通さないため、実IMEの合格にはしない。Schannelの存在と初期化を、HTTPS/WSSの実TLS handshakeの成功とは扱わない。GUI契約はプレビュー、Diagnosticsの展開・更新・画像解放、設定、テーマ操作を含むが、全Qt Widgets APIや未使用のQt Quick/RHI描画経路の互換性を保証する試験ではない。

## 保守コストと比較への適用

アプリ固有の例外処理・回避用UIコードは増えていない。追加はmanifestの1 feature、CMakeのfeature選択とdeployオプション、helperの構成名、CIのB/C行と分離先、削減対象の再収集を拒否する検証、および独立テストである。Qt/OpenCVへの独自patchや配布後の削除リストはない。一方、Qt更新時には明示feature一覧と除外pluginが引き続き妥当か確認する必要があり、CIはQtを3構成検証する分だけ増える。

検証したGUI機能では軽量化が有効だったため、[3候補の容量比較](comparison.md)にはCの **展開後45.20MB / ZIP 17.55MB** を追加して使用する。A/Bの値と再現経路は残し、Qtの標準構成を上書きしたり、アプリの既定をCへ切り替えたりはしない。

容量の差をGUIライブラリの採用理由にはしない。[共通GUIの保守性・未達事項](comparison.md)は引き続き評価対象。今回の最適化構成の性能や30分動作は再測定しておらず、[180秒×3回の性能測定](performance-180s-3.md)のQt値はA標準構成の結果である。NDIの同梱・受信、実Scenario Runtime、完全移植版の容量推定は今回も対象外。

## 再現と根拠

[READMEのA/B/C手順](../README.md#qtの軽量化検証a--b--c)で、新規配布先に生成する。baseline・Qt/OpenCVのoverrideは変更しない。各構成の `report.json` / `files.csv` と内側ZIPをActions Artifactへ保存する。既存のAと前回の性能測定結果はそのまま残す。

根拠は固定baselineの[qtbase manifest](https://github.com/microsoft/vcpkg/blob/9e593bb18ea69cc5095e012465dcd675a822ed0d/ports/qtbase/vcpkg.json)、[vcpkg feature仕様](https://learn.microsoft.com/en-us/vcpkg/concepts/features)、[Qt配布オプション](https://doc.qt.io/qt-6/windows-deployment.html)、[CMake Deploy API](https://doc.qt.io/qt-6/qt-generate-deploy-app-script.html)、[IMEイベントAPI](https://doc.qt.io/qt-6/qinputmethodevent.html)。公開ドキュメントの現行版と固定版を区別し、6.11.1のローカルAPIと `windeployqt --help` でもオプションの存在を確認した。
