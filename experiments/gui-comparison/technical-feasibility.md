# Phase 1：技術条件の調査（2026-10-23）

比較対象はQt Widgets、wxWidgets、Dear ImGuiの3候補。公式資料と固定vcpkg checkoutの調査に加え、ローカルの共通GUI・配布起動を検証した。クリーンCIの結果は実行後に追記する。資料確認だけで合格・不合格・採用にはしない。

## 候補ごとの経路

| 実装 | 第一候補の取得・ビルド経路 | 固定vcpkg baselineで確認できた版 | 配布・追加管理の確認事項 | 実測状態 |
| --- | --- | --- | --- | --- |
| Qt Widgets | vcpkg / CMake / Ninja | qtbase 6.11.1#1 | Qt Deploy、plugins、LGPLとthird-party通知 | 共通GUI・小規模/大量CTest・配布/ZIP展開後起動がローカル成功 |
| wxWidgets | vcpkg / CMake / Ninja | wxwidgets 3.3.1#1 | MSWのcontrolとDataView、DLL、イベントと画像寿命、標準featureの推移依存 | 共通GUI・小規模/大量CTest・配布/ZIP展開後起動がローカル成功 |
| Dear ImGui | vcpkg / CMake / Ninja、Win32 + D3D11 backend | imgui 1.92.8#1 | platform/renderer backend、フォント、テクスチャ寿命、ファイル選択手段 | 共通GUI・小規模/大量CTest・配布/ZIP展開後起動がローカル成功 |

baselineはPR #152と同じ `9e593bb18ea69cc5095e012465dcd675a822ed0d`。`vcpkg.json` に3候補のfeatureとoverrideを固定した。vcpkg本体もこのcommitで照合する。Dear ImGuiの標準portはstatic-onlyで、公式Win32/DX11 backendを含めてexeへリンクする。

## 公式資料で確認した点

- **Qt Widgets**：[Qt 6.11のライセンス説明](https://doc.qt.io/qt-6.11/licensing.html) は、moduleごとにLGPL/GPL等の条件が異なること、third-party codeの条件が別にあることを明示している。Widgetsの実際の同梱moduleと通知を確認する。
- **wxWidgets**：[公式ライセンス](https://wxwidgets.org/about/licence/) のwxWindows例外を含む条件と同梱文書を確認する。
- **Dear ImGui**：[MITライセンス](https://github.com/ocornut/imgui/blob/master/LICENSE.txt) と [公式backend説明](https://github.com/ocornut/imgui/blob/master/docs/BACKENDS.md) を確認する。Win32/D3D11はこの比較の通常backendの候補で、独自描画エンジンを作ることを前提にしない。追加test engineの利用条件は本体のMITと同一と仮定しない。

各ライセンスの実配布検証は、選んだ固定リリースに同梱される原文、third-party通知、必要な帰属表示とソース参照まで保存して確認する。master/latestの説明は取得経路の調査にのみ使い、配布する版の原文を代用しない。

## Phase 1の実測による完了条件

3候補の各々について、固定情報からC++23 / MSVC / x64 Releaseの最小shellを構築し、必要なGUIランタイムとOpenCVを収集したZIPを新規フォルダーへ展開して起動する。バージョン・構築ログ・通知文書・起動ログを残す。これはPhase 2のMonitor/Diagnostics/Profile合格とは別のチェックとする。

候補固有のbackend、control、ビルド・配布手順や回避策が必要なら、その実装量・維持作業を後続の保守性評価へ引き継ぐ。
