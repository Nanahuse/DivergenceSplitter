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

## 検証状態

追加実装を作成中。ローカル・CIのQt Quick実測値、契約試験、画面、性能結果は完了後に追記する。既存3候補の成功をQt Quickの成功とは記録しない。

標準Qtと同じ依存を基準にするため容量最適化は未実施。実物IME、物理入力、DPIの実モニター移動、GPUメモリ・実presentは未検証。既存候補の30分反復記録は保持し、Qt Quickの長時間試験へ転用しない。

## 保守性評価の範囲

QMLレイアウトとC++の型境界・QObjectの寿命・model/provider管理を別に記録する。Scenario.enabledは既存共通モックに合わせて初版から実装するため、既存3候補で実施した独立した仕様変更実験の差分量と直接比較しない。初版で含めた実装を「後から同じ変更を適用した結果」とは扱わない。

公式手順：[QML moduleとリソース](https://doc.qt.io/qt-6/qt-add-qml-module.html)、[QMLアプリの配布](https://doc.qt.io/qt-6/qt-generate-deploy-qml-app-script.html)、[TreeView](https://doc.qt.io/qt-6/qml-qtquick-treeview.html)。実際のビルドは固定6.11.1を使用する。
