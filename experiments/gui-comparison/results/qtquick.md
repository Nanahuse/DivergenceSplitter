# Qt Quick追加検証（2026-10-24）

Qt Widgets、wxWidgets、Dear ImGuiの既存結果を保持し、Qt Quickだけを新たに検証する。採用決定、NDI、本体移植は対象外。

## 実装と再現方法

共通の標準C++23モック、OpenCV 4.12.0#7、Release/MSVC、既存ZIP条件を使用する。vcpkg baselineと既存候補のfeatureは変更しない。追加feature `qtquick` は標準qtbase 6.11.1#1とqtdeclarative 6.11.1を選択する。Widgetsの軽量配布CはQt Quick/RHIへ適用しない。

`qtquick/main.cpp` はQGuiApplication、QML用モデル、image provider、共通モックへの操作、契約試験のadapterを担当する。`qtquick/Main.qml` はQt Quick Controls/Fusion、TreeView、ProfileフォームとQt Quick Dialogsを担当する。QStandardItemModelはQtGuiに属し、Widgets画面の埋め込みは行わない。

Diagnosticsは安定IDとmodel indexを保持して行を差分更新する。値更新は可視行のみ。非表示時にモデル・参照画像を解放する。画像はGUIスレッドの同期image providerから所有権を持つQImageとして渡し、latest-onlyモックを67ms周期で取り込む。workerからGUIへのイベントキューは追加しない。

Developer PowerShellで固定vcpkg checkoutをVCPKG_ROOTに設定して実行する。

```powershell
tools/build_gui_comparison.ps1 -Candidate qtquick
python tools/run_gui_comparison.py --distribution dist/gui-comparison --output build/qtquick-measurements-180s-3 --candidates qtquick --warmup 30 --seconds 180 --repeats 3 --diagnostics-repeats 3 --soak 0
```

ビルド先・配布先・レポート先はそれぞれ`build/gui-comparison/qtquick`、`dist/gui-comparison/qtquick`、`build/gui-comparison-reports/qtquick`。Qtの公式CMake QML deployment scriptでQML importsとDLLを収集し、配布検証ツールで所有パッケージ、通知、開発ファイル混入、展開後GUI契約を確認する。

ローカルの深いworkspaceでは、qtdeclarativeのDebug生成ファイル`QQmlNativeDebugServiceFactoryPlugin`のコンパイルでC1083 / Invalid argumentが発生した。依存版を変更せず、workspaceへの一時的な短いドライブ割当とvcpkg標準のbuildtrees/packages rootオプションで再試行して成功した。既存候補のbuildtreeは変更していない。

```powershell
# V:が未使用であることを確認してからworkspaceを割り当てる。
subst V: (Get-Location).Path
build/vcpkg/vcpkg.exe install --triplet x64-windows --x-manifest-root=experiments/gui-comparison --x-feature=qtquick --x-install-root=build/gui-comparison/qtquick/vcpkg_installed --x-buildtrees-root=V:/build/qtquick-buildtrees --x-packages-root=V:/build/qtquick-packages
# 依存ビルド完了後、不要になった一時割当を解除する。
subst V: /D
```

helperはQt Quickについてのみ`GUI_VCPKG_SCRATCH`の指定を受け、同じvcpkg標準オプションをCMakeへ渡せる。Windows CIはrunnerの短いtemp配下を使い、その依存ビルドログもArtifactへ保存する。既存候補の手順には適用しない。

## 検証状態

ローカルではReleaseビルド、CTest 7件、検証ツール48件、配布small / ZIP展開largeのGUI契約を通過した。共通13チェックに、QML画像delegateの読み込みと、配布内のQML import / Qt DLL解決を追加する（配布契約は各15チェック）。QML実行時警告も失敗として扱う。実際の描画APIはDirect3D11だった。

| ローカル実測 | Qt Quick |
| --- | ---: |
| ファイル数 | 244 |
| 本体exe | 320,000 bytes |
| GUI・依存・plugin | 100,769,885 bytes |
| OpenCV・依存 | 10,115,072 bytes |
| GUI/OpenCV共有依存 | 1,012,224 bytes |
| Windows SDK graphics runtime | 20,568,368 bytes |
| MSVC Runtime | 1,646,032 bytes |
| 通知・metadata | 10,101,888 bytes |
| その他 | 1,153 bytes |
| 展開後 | **144,534,622 bytes（144.53MB）** |
| 配布ZIP | **55,861,408 bytes（55.86MB）** |

ZIPは既存と同じDEFLATE level 6、固定日時・パス順、Python 3.14.6 / zlib 1.3.1.zlib-ng。外側Actions Artifactの値ではない。[ファイル別明細](qtquick/local/files.csv)、[配布レポート](qtquick/local/report.json)、[時間](qtquick/local/timings.json)、[CTest](qtquick/local/gui-tests.xml)、[配布起動](qtquick/local/installed-smoke.json)、[ZIP起動](qtquick/local/zip-smoke.json)を保存した。

画面も確認した：[Diagnostics](qtquick/local/diagnostics-view.png)、[暗色Profile](qtquick/local/profile-view.png)、[Monitor](qtquick/local/small-gui.png)。暗色の日本語placeholderは視認できるが、IME操作の証拠とはしない。

既存ローカルのQt Widgets Aは107,513,348 / 44,273,201 bytes、Cは45,204,525 / 17,560,717 bytes、wxWidgetsは25,706,636 / 9,215,371 bytes、Dear ImGuiは14,703,267 / 5,486,109 bytes（展開後 / ZIP）。これらは再測定せず以前の値を参照する。Qt Quickは標準Qtを使い、Widgets Cと同じ依存削減を行った値ではない。

## Windows CIと配布容量

source `f7c49659e9a9baaa4e14708b5865a20984a5b95f` の[Windows CI run 40074825462](https://github.com/Nanahuse/DivergenceSplitter/actions/runs/40074825462)は成功した。GUI比較ジョブはQt Quickだけ。クリーンなWindows 2025 runner上で依存解決、Releaseビルド、CTest 7件、検証ツール48件、配布smallとZIP展開largeの各15チェックを確認した。QML importとQt DLLが配布root内で解決されることも確認した。既存3候補のnative試験・性能測定は再実行していない。

| 容量（実測、MB=1,000,000 bytes） | ローカル | Windows CI |
| --- | ---: | ---: |
| 展開後 bytes | 144,534,622 | **144,484,013** |
| 配布ZIP bytes | 55,861,408 | **55,850,373** |
| 展開後 MB | 144.53 | **144.48** |
| 配布ZIP MB | 55.86 | **55.85** |
| ファイル数 | 244 | 244 |
| 外側Actions Artifact bytes | 対象外 | **56,515,341** |

外側[配布Artifact](https://github.com/Nanahuse/DivergenceSplitter/actions/runs/40074825462/artifacts/12554852947)は内側の`qtquick.zip`にログ・画面・レポートを加えた別アーカイブ。別の診断Artifactは20,634,302 bytesで、配布容量には加算しない。同じZIP条件でもローカルは展開後+50,609 bytes / ZIP +11,035 bytes。SDK graphics DLL、Qt/OpenCVのバイナリ、通知metadataの差があり、byte単位の再現性を実証したとはしない。

CIの分類はGUI・依存・plugin 100,784,221 bytes、OpenCV・依存10,112,000、共有依存1,012,224、SDK graphics 20,506,392、MSVC Runtime 1,646,032、通知・metadata 10,101,991、本体320,000、その他1,153。所有関係で分類し、共有DLLは一度だけ数える。[CIファイル明細](qtquick/ci/files.csv) / [配布レポート](qtquick/ci/report.json) / [CTest](qtquick/ci/gui-tests.xml) / [ツール試験](qtquick/ci/tool-tests.xml) / [配布起動](qtquick/ci/installed-smoke.json) / [ZIP起動](qtquick/ci/zip-smoke.json) / [CI出所](qtquick/ci/provenance.json)。

ローカルの大きなファイルはICU data 33.11MB、dxcompiler 14.32MB、Qt6Gui 7.00MB、Qt6Quick 6.29MB、OpenSSL crypto 5.36MB、Qt6Core 5.31MB、Qt6Qml 5.02MB、d3dcompiler_47 4.74MB。標準QtBaseを使う今回の値に対し、Widgets B/Cで行ったfeature削減やcompiler DLL除外は適用していない。Qt Quickの容量最適化は別の検証が必要。

### CI所要時間と依存cache

初回[40071443017](https://github.com/Nanahuse/DivergenceSplitter/actions/runs/40071443017)は37 packageをcacheから復元した後、qtdeclarative Debugの生成ファイル（FluentWinUI3 style）でC1083 / Invalid argumentとなり失敗した。途中までの33分は成功した導入時間ではない。短いscratch rootを設定した上記の修正版CIでは成功した。独自port/patchや依存バージョン変更は不要だったが、短いパスの管理は追加の運用コストとなる。

| CI実測（修正版run） | 時間 |
| --- | ---: |
| ジョブ全体（checkout、upload等を含む） | **83分57秒** |
| configure・依存導入 | 4,848.67秒 |
| Releaseビルド | 13.87秒 |
| CTest | 24.93秒 |
| install・deploy | 10.01秒 |
| 配布検証・ZIP生成・展開後起動 | 17.89秒 |
| helper合計 | 4,915.55秒 |

41 package中37を復元し、qtsvg、qtshadertools、qtlanguageserver、qtdeclarativeをビルドした。qtdeclarativeの処理は約72分56秒（Debug/Releaseとcache処理を含む）。全依存の完全cold時間は**未測定**。ローカルのqtdeclarative約35分とCIの差はマシン・ビルド環境の差を含む。成功後に完全な依存cacheを保存した。[時間JSON](qtquick/ci/timings.json)と[cache・依存ログ抜粋](qtquick/ci/dependency-timing.txt)を参照。

## Qt Quickの性能測定（180秒×3回）

MonitorとDiagnosticsを各180秒×3回、84 / 10,220ノードの両データ規模、合計**12ケース**で完了した。各回30秒warmup、30分試験は追加していない。2026-10-24 07:37:43–08:19:45 UTC、source `f7c4965`、clean treeで開始した。同じWindows 11 10.0.26200、AMD64 Family 25 Model 116、12 logical CPUs、Balanced電源で直列測定。描画APIはDirect3D11だったが、GPU adapterのハードウェア/WARP区別は測っていない。

CPUは共通workerを含むプロセスのCPU秒÷実測秒×100、1 logical core=100%。private/working setは約500ms間隔の観測値でGPUメモリを含まない。下表はCPUが3回の中央値（最小–最大）、private/working setが3回中の最大観測peak、MBはdecimal。

| 画面 | ノード数 | CPU % | private peak MB（最大） | working set peak MB（最大） |
| --- | ---: | ---: | ---: | ---: |
| Monitor | 84 | 18.86（18.43–19.60） | 130.19 | 126.63 |
| Monitor | 10,220 | 21.50（21.31–24.24） | 136.70 | 131.06 |
| Diagnostics | 84 | 14.78（12.84–15.75） | 113.94 | 114.67 |
| Diagnostics | 10,220 | 14.02（14.01–14.03） | 136.57 | 135.12 |

Monitorの生成は約59.996Hz、取込は14.924Hz。各回p95の中央値はsmall 18.27ms / large 18.32ms、process生成から初回取込は350.14 / 369.49ms。取込時刻の値であり、実画面presentや操作応答ではない。Diagnosticsではpreview取込0、値更新2,686回/180秒、測定区間の階層再構築0回。参照画像要求1回はwarmup前に読み込んだ累積値で、測定中に毎回生成したという意味ではない。

3分区間の最初と最後の1分のprivate中央値差は全12件で−266,240〜+118,784 bytes。観測サンプルの最大間隔は約0.54秒。長時間のリーク不在を示す試験にはしない。測定中だけsystem/display実行要求を使い、終了後に解除した。電源プランやロックポリシーは変更していない。前景・遮蔽や他のデスクトップ活動は統制していないため、候補の普遍的な性能順位は付けない。

[集計JSON](qtquick/performance-180s-3.json) / [12件の生データ・画面・環境](qtquick/measurements-180s-3/) / [電源要求の範囲](qtquick/measurement-power.json) / [測定後のSHA256照合](qtquick/measurement-provenance.json)。測定後もsource fingerprintと配布244ファイルが開始時の記録と一致し、exe/DLLの差替えはなかった。既存3候補は[以前の36ケース](performance-180s-3.md)を参照し、今回再測定しない。

標準Qtと同じ依存を基準にするため容量最適化は未実施。実物IME、物理入力、DPIの実モニター移動、GPUメモリ・実presentは未検証。既存候補の30分反復記録は保持し、Qt Quickの長時間試験へ転用しない。

## 保守性評価の範囲

QMLレイアウトとC++の型境界・QObjectの寿命・model/provider管理を別に記録する。Scenario.enabledは既存共通モックに合わせて初版から実装するため、既存3候補で実施した独立した仕様変更実験の差分量と直接比較しない。初版で含めた実装を「後から同じ変更を適用した結果」とは扱わない。

追加の手書き実装は`main.cpp` 400行、`Main.qml` 485行、配布内runtime検査用`runtime_check.hpp` 42行（空行・include・自動操作を含む物理行数）。生成されたQML/C++、vcpkg、共通モックは除く。既存3候補の圧縮したC++とQMLの整形規則が異なり、合計行数だけで保守性を順位付けしない。

独自の管理はController、ProfileModel、Images、DiagnosticsのID/item対応、QML testAction adapter。Profileのdraftを共通層だけに保持し、QMLはroleとsetterで編集する。画面レイアウトは宣言的に分離できたが、role名・NOTIFY・QML binding・delegate再利用時の挙動をC++とQMLの双方で維持する必要があった。engineをcontroller/sessionより先に破棄し、画像providerの所有とworker joinの順序を明示した。Qt Widgetsと同様、階層差分と画像寿命の責任は残る。

追加時に必要だった調整は、CTestの開発用QML/DLL検索パス、`qt_add_executable`によるQML deployment情報の記録、既存Windows manifestのtarget source指定、TreeViewの全階層での2列固定、削除・再利用行の未定義display値を空文字にするbindingだった。最後の2点は画面確認と実行時警告で検出した。独自の汎用controlは追加せず、TreeViewDelegateのcontentItemをLabelで指定するが、このbindingの維持もQt Quick側のコストとして扱う。

公式手順：[QML moduleとリソース](https://doc.qt.io/qt-6/qt-add-qml-module.html)、[QMLアプリの配布](https://doc.qt.io/qt-6/qt-generate-deploy-qml-app-script.html)、[TreeView](https://doc.qt.io/qt-6/qml-qtquick-treeview.html)。実際のビルドは固定6.11.1を使用する。
