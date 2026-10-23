# GUI比較の実測記録

採用候補は未決定。対象はQt Widgets、wxWidgets、Dear ImGui。NDI・実Scenario Runtimeは全候補から除外する。PR #152の最小Qtアプリと、この共通GUIは別の検証対象。

## ローカルの機能・配布検証

変更前 `9a96bf7`、同じScenario.enabled仕様変更後 `7d91470`。以後、展開中Detector削除・snapshot寿命・周期・ツールチェーンを検証し、最新のローカル測定版は `786350a`。3候補ともC++23 / MSVC / x64 Release、CTest 6件に成功した（共通契約1、小規模84ノードと大量10,220ノードのGUI契約2、Diagnostics/暗色Profileの起動・画面保存2、長押し途中の終了1）。配布フォルダーの小規模テストと、ZIP新規展開先の大量テストも開発用PATHを除いて成功した。配布・集計検証ツールのpytestは25件成功。Ruff・tyはリポジトリ全体で成功。

| 候補 | 展開後 bytes | 配布ZIP bytes |
| --- | ---: | ---: |
| Qt Widgets | 107,513,348 | 44,273,201 |
| wxWidgets | 25,706,636 | 9,215,371 |
| Dear ImGui | 14,703,267 | 5,486,109 |

Python 3.14.6 / DEFLATE level 6、順序・日時正規化は全候補同一。ImGuiの公式backendを含む静的リンク分はexeに計上する。DLLの共有依存は一度だけ計上する。大きいファイル・分類・SHA256・ビルド環境は [要約JSON](local-distribution.json)、ファイル全件CSV・ZIP・GUI生ログはビルド出力に保存した。ローカルでは既存binary cacheを利用しているため、依存導入時間をコールドビルド時間とは呼ばない。

## Diagnosticsと状態管理の実装

| 対象 | Qt Widgets | wxWidgets | Dear ImGui |
| --- | --- | --- | --- |
| 階層 | QTreeView / QStandardItemModel、安定ID→item対応 | wxTreeListCtrl、安定ID→item対応 | TreeNodeEx / Table、安定ID、親→子の対応 |
| 値更新 | 可視行のdataを更新、構造は再生成しない | 展開された枝のitem textを更新 | snapshotを周期更新して宣言、構造対応は変更時だけ構築 |
| 展開・スクロール | native viewが保持 | DataViewが保持 | ImGui StateStorageとアプリ側の展開要求 |
| 参照画像 | QLabel/QPixmapを展開時に作成、collapse/非表示で解放 | wxStaticBitmap/wxBitmapを展開時に作成、collapse/非表示で解放 | D3D11 texture/SRVを展開時に作成、wanted集合から外れたら解放 |
| Profile | QTableWidget / check-state / signals | wxGrid / bool editor / events | InputText・InputInt・Checkbox、draftを直接編集 |
| ダイアログ | QFileDialog / QMessageBox | wxFileDialog / wxMessageDialog | IFileOpenDialog / MessageBox、COM寿命の管理 |
| platform/render | QApplication / Widgets | wxApp / MSW | Win32 window/message loop、D3D11 swapchain・resize・texture・DPI処理 |

3候補ともUI以外のworkerからGUIを直接呼ばず、GUI所有のタイマー／ループでimmutableなlatest snapshotを採用する。状態のイベントキューは作らず、映像生成と画面更新を分離した。停止時はworkerをjoinする。各候補に独自の汎用controlライブラリは追加していない。

wxTreeListCtrlはcollapseイベントを直接公開しないため、公開GetView/DataView APIでcollapseを受けて遅延処理する。スクロール位置取得もDataViewのGetViewStartを使う。ImGuiは公式backendを使用しているが、device、swapchain、画像ハンドル、ファイル選択、テーマ/DPIの接続はアプリ側の責任となる。Qt/wxも安定ID対応表と差分削除・参照画像寿命の管理は必要だった。

参照画像の要求はUIが保持するimmutableな階層snapshotで検証する。worker側でDetectorが削除された直後にも、UIが読んでいる旧snapshotの寿命を保ち、次の構造同期で画像を解放する。3候補とも「動的Detectorを展開してから削除し、その画像だけが解放され、生存Detectorの展開が残る」操作を追加検証した。共通workerは20回のstart/joinも検証する。

**wxWidgetsの起動後のnativeテーマ切替は未達。** [固定版3.3.1の実装](https://raw.githubusercontent.com/wxWidgets/wxWidgets/v3.3.1/src/msw/darkmode.cpp) は、既存top-level windowがある場合にSetAppearanceからCannotChangeを返す。試作では戻り値を確認して「Theme: restart required」と表示する。全候補へ同じ `--dark` を追加し、起動時の暗色Profile表示は3候補とも画面保存で確認した。wxはウィンドウ作成前の指定が必要。再起動による設定引継ぎや独自配色は追加実装していない。自動checkの `U01_theme_resize_handlers` は操作handlerの実行だけで、全候補の実行中テーマ切替合格を意味しない。

15Hz取込の校正では、ImGuiの期限更新方式に遅延の累積があり、期限位相を維持して期限超過を捨てる共通PreviewCadenceへ修正した。wxTimerの67ms指定は約12.6Hzとなったため、16msのnative heartbeatから同じ共通期限でUIのpayloadを更新する形へ調整した。追加の独自timer/描画基盤は作っていない。2秒warmup + 15秒の確認ではQt約14.90Hz、wx約14.99Hz、ImGui約14.98Hz。これは校正値であり、5回の定常計測の結果とは区別する。調整前のログは保存するが、同条件の性能比較には含めない。

日本語MSVC/CMakeの接頭辞の文字化けにより、古いローカルビルドでヘッダー依存が0件となり、ABI不整合の異常終了を検出した。UTF-8コードページでfresh configureとclean buildを行い、Qt adapterのヘッダー依存265件と全GUI契約の再成功を確認した。全候補の共通ビルドhelperへ対策を入れた。GUIライブラリ固有の不安定性とは扱わない。

## 同じ仕様変更による評価

変更は「Scenario.enabledをdraft/Apply、Monitorカード、Diagnostics、未保存確認へ反映」。初版から独立した [変更commit](https://github.com/Nanahuse/DivergenceSplitter/commit/7d91470) で差分を確認できる。

| アプリ固有UIファイル | 追加行 | 削除行 | 変更箇所 |
| --- | ---: | ---: | --- |
| Qt Widgets | 9 | 6 | checkbox列、itemChanged、form同期、カード・値表示、操作driver |
| wxWidgets | 21 | 8 | bool列、cell event、form同期、カード・値表示、操作driver、終了時report例外処理 |
| Dear ImGui | 7 | 6 | checkbox列、カード・値表示、公開IO操作driver |

共通層はenabledを設定・階層・評価値へ追加し、無効Scenarioのactive/connectedを抑制した。動的に追加される子ノードにも有効状態を継承する必要があった。テストは失敗Applyによる漏出、既存snapshotの不変性、安定ID、他Scenarioへの非波及、discard、新規Scenarioの既定値を確認する。実GUIでも編集・Apply・enabledだけの未保存変更を取消してdraftが残ることを確認した。

この差分は一つの小変更の証拠であり、行数だけで保守性を順位付けしない。wxの行数には可読性のための整形と終了時の例外処理も含む。共通層・テスト変更は全候補に同じものを使用する。

## 未検証・評価中

- クリーンWindows CI、初回依存構築時間、キャッシュ利用時、外側Artifact容量は実行結果を追記する。
- 定常CPU・メモリ・フレーム取込周期、長時間のメモリ推移、画面切替反復は測定結果を追記する。
- GUI自動試験はアプリ内のコントロールAPI・イベント・ImGui公開IOによるもの。実ダイアログの取消は確認したが、物理入力・IME・ファイル選択の確定・実モニター間のDPI移動は未検証。
- 値更新時の展開と数値スクロール位置は確認。削除されたアンカーノードの代替位置と画面再表示時の復元は追加評価を要する。
- 画面への実present遅延・操作応答遅延は未測定。数秒の機能試験のCPU値を定常性能の代用にしない。

未検証項目を合格にせず、ここまでの容量や実装量から採用決定を行わない。

## 初回CIで確認した失敗への対処

初回run `39949952919` のwxは依存構築が完了した後、旧版の大量ノード試験が `Large Diagnostics did not actually scroll` で失敗した。固定時間だけ待っていた判定を、実際に非ゼロ位置へスクロールできたことを待つ方式へ変更した。要件は緩めず、値更新中の位置・展開保持も確認する。修正版のCIで解消を検証する。

この失敗では、ジョブ成功時だけ保存する既存cache手順により、構築済み依存のcacheも保存されなかった。restore/saveを明示し、依存configure完了後なら後続のアプリ・GUI試験が失敗しても完全な依存cacheを保存する。依存構築途中の不完全なcacheは保存しない。依存設定・baseline・配布内容の変更はない。
