# GUI比較の実測記録

採用候補は未決定。対象はQt Widgets、wxWidgets、Dear ImGui。NDI・実Scenario Runtimeは全候補から除外する。PR #152の最小Qtアプリと、この共通GUIは別の検証対象。

## ローカルの機能・配布検証

変更前 `9a96bf7`、同じScenario.enabled仕様変更後 `7d91470`。変更後の3候補はC++23 / MSVC / x64 Release、共通CTest、小規模84ノードと大量10,220ノードのGUI契約に成功した。配布フォルダーの小規模テストと、ZIP新規展開先の大量テストも開発用PATHを除いて成功した。配布検証ツールのpytestは22件成功。Ruff・tyはリポジトリ全体で成功。

| 候補 | 展開後 bytes | 配布ZIP bytes |
| --- | ---: | ---: |
| Qt Widgets | 107,510,788 | 44,271,585 |
| wxWidgets | 25,703,564 | 9,213,678 |
| Dear ImGui | 14,699,683 | 5,484,813 |

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
