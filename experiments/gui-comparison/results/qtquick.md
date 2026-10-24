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

ローカルの深いworkspaceでは、qtdeclarativeのDebug生成ファイル`QQmlNativeDebugServiceFactoryPlugin`のコンパイルでC1083 / Invalid argumentが発生した。依存版を変更せず、workspaceへの一時的な短いドライブ割当とvcpkg標準のbuildtrees/packages rootオプションで再試行する。既存候補のbuildtreeは変更しない。

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

CI初回[40071443017](https://github.com/Nanahuse/DivergenceSplitter/actions/runs/40071443017)は37 packageをcacheから復元した後、qtdeclarative Debugの生成ファイル（FluentWinUI3 style）でC1083 / Invalid argumentとなり失敗した。qtdeclarativeの途中まで33分で、成功した導入時間ではない。ローカルの短いbuildtreeではqtdeclarativeを約35分で構築・cache保存できた。CIにも短いscratch rootを設定して再検証する。依存の完全cold時間とは区別する。

Qt QuickのみのMonitor / Diagnostics各180秒×3回（小規模・大量の12ケース）と、修正版CIの結果は継続して記録する。既存3候補は再実行しない。

標準Qtと同じ依存を基準にするため容量最適化は未実施。実物IME、物理入力、DPIの実モニター移動、GPUメモリ・実presentは未検証。既存候補の30分反復記録は保持し、Qt Quickの長時間試験へ転用しない。

## 保守性評価の範囲

QMLレイアウトとC++の型境界・QObjectの寿命・model/provider管理を別に記録する。Scenario.enabledは既存共通モックに合わせて初版から実装するため、既存3候補で実施した独立した仕様変更実験の差分量と直接比較しない。初版で含めた実装を「後から同じ変更を適用した結果」とは扱わない。

追加時に必要だった調整は、CTestの開発用QML/DLL検索パス、`qt_add_executable`によるQML deployment情報の記録、既存Windows manifestのtarget source指定、TreeViewの全階層での2列固定、削除・再利用行の未定義display値を空文字にするbindingだった。最後の2点は画面確認と実行時警告で検出した。独自の汎用controlは追加せず、TreeViewDelegateのcontentItemをLabelで指定するが、このbindingの維持もQt Quick側のコストとして扱う。

公式手順：[QML moduleとリソース](https://doc.qt.io/qt-6/qt-add-qml-module.html)、[QMLアプリの配布](https://doc.qt.io/qt-6/qt-generate-deploy-qml-app-script.html)、[TreeView](https://doc.qt.io/qt-6/qml-qtquick-treeview.html)。実際のビルドは固定6.11.1を使用する。
