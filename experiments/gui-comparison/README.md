# GUIライブラリ比較

採用ライブラリは未決定。比較対象は **Qt Widgets、wxWidgets、Dear ImGuiの3候補** とし、同じ仕様・合格条件で比較する。PR #152はQt Widgetsの依存・配布経路の証拠として再利用するが、共通GUI仕様の合格証拠や選定結果にはしない。

このディレクトリーは比較用の実験であり、Scenario Runtimeや製品GUIの移植ではない。NDIは全候補から除外する。

## 共通仕様と合格条件

現行仕様の参照元は `packages/divergencesplitter-ui/src/divergencesplitter_ui/monitor/` と `configuration/`。特に `diagnostics.py`、`input_preview.py`、`reset_all.py`、`configuration/actions.py` と対応するテストを参照する。現行版はProfileの保存時にreloadするが、この実験ではユーザー指定のApply操作を共通境界として明示する。

| ID | 共通の操作・期待する画面上の挙動 | 必要な証拠 |
| --- | --- | --- |
| M01 | Monitorで入力・処理・通信状態と複数Scenarioのカードを表示する | UI操作とバックエンドの値の照合 |
| P01 | 60Hzの入力から最新フレームを最大15Hzで取り込む。古いフレームを順に再生しない | 生成／表示sequence、時刻、滞留数 |
| D01 | Scenario → Rule → Condition → Detectorを表示する | 小規模・大量データ双方の操作記録 |
| D02 | スコア・状態更新で展開状態とスクロールのアンカーを保持する | 値更新前後のUI状態とノードID |
| D03 | ノード追加・削除後も生存ノードのIDを維持する | 変更前後のIDと表示の整合性 |
| D04 | Diagnostics非表示中は階層の構築・差分・参照画像生成を行わない | 可視性切替と処理カウンター |
| D05 | Detectorの参照画像を展開時にだけ生成し、閉じる／画面を離れる／削除する際に解放する | 参照要求回数とUI側resident画像数 |
| C01 | 入力ソース選択、Scenario追加・削除・編集はdraftだけを変更する | draft / appliedの比較 |
| C02 | Applyで検証する。空名・重複名・範囲外の値を拒否し、失敗時はappliedを変更しない | 実UI入力と共有コマンドの結果 |
| C03 | ファイル選択の取消は状態を変えず、未保存変更の確認で続行／取消を選べる | 実ダイアログ操作。モックだけの成功とは区別 |
| R01 | Reset Allは連続2秒で1回発火。解放、キャンセル、フォーカス喪失、画面離脱、破棄で中止 | 仮想時計の境界テストと実GUIのイベントテスト |
| L01 | 開始・停止・再開始、画面切替中・長押し中の終了で安全に破棄する | 操作反復、終了コード、worker停止、リソース数 |
| U01 | 800×600〜1920×1080、100/150/200% DPI、明暗テーマで操作できる | 実画面の記録。CIの状態テストだけで合格にしない |

値更新で保持するスクロール位置は、数値ピクセル位置だけでなく「先頭に見える安定IDと相対位置」で確認する。構造変更でアンカーノードが削除された場合は最寄りの生存ノードへ移り、例外にしない。画面を離れた際は参照画像とresident階層を解放する。再表示時の展開・スクロール復元は別途記録し、値更新時の保持と混同しない。

ImGuiの毎フレームの宣言呼び出しと、retained-modeのウィジェット破棄・再生成を同一視しない。比較するのは利用者の挙動、永続状態の管理量、実際の画像生成・モデル再構築・描画負担。特定のTreeViewや共通の描画層は要求しない。

## データとスレッド境界

共通層は標準C++23型だけを公開する。Qt型、wx型、ImGui型、OpenCVのMat、各UIのコールバックやdispatcherを公開境界へ入れない。UIアダプターがイベントループ、描画、binding、モデル通知、画像ハンドルの所有と破棄を実装する。

- immutableな階層と安定ID、値のsnapshot、RGBA画像、入力設定を渡す。
- 映像と状態はlatest-onlyの共有スロットを使い、毎フレームのイベントやsnapshotを無制限に蓄積しない。
- producerはUIコールバックを呼ばない。通知を選ぶ実装はUI側でcoalesceし、pending通知は最大1件にする。
- 終了時はworkerをjoinしてからバックエンドを破棄する。UI側画像ハンドルはUIスレッドで解放し、producerはそれに触れない。スナップショットは所有権付きで読み、別スレッドが変更中のバッファをUIへ貸さない。
- 設定のdraft、Apply後の設定、runningの状態を分離し、Apply失敗のエラーを表示する。
- OpenCVの参照画像デコード・基本処理は共通の画像層で行い、全候補で同じPNG入力とパラメーターを使う。GUIごとに処理アルゴリズムを再実装しない。

小規模は3 Scenario × 3 Rule × 4 Condition（各ConditionにDetector）で84ノード。大量データは20 × 10 × 25で10,220ノード。入力画像は1280×720 RGBA、参照画像は160×90とする。構造変更は操作シナリオの明示コマンドで行い、ノードIDを再利用しない。入力60Hz／UI画像取込15Hzを共通条件とし、値表示の更新頻度も記録する。OSのスケジューラーの誤差をフレームキューで取り戻さない。

## 試験と測定

| 試験 | 操作 | 記録 |
| --- | --- | --- |
| 短時間の機能試験 | 開始、Monitor、Diagnostics、展開、値更新、構造変更、Profile編集、Apply、取消、Reset、停止 | 各要件のpass/fail、利用したUI部品とテスト経路 |
| 切替・破棄試験 | 100回の画面切替、20回の開始・停止、画像展開中と長押し中の終了 | 例外、残存worker、resident画像数、イベント滞留 |
| 短時間測定 | Monitor・Diagnosticsを各30秒warmup + 180秒測定、各3回、両データ規模 | CPU時間、working set / private bytes、最新画像の取込遅延、初回取込時間。実画面presentと物理応答は未測定 |
| 長時間測定 | 30分、両データ規模 | private bytesの推移、表示sequenceの進行、参照画像解放 |
| 手動表示試験 | リサイズ、スクロール、明暗テーマ、DPI変更、実ファイルダイアログ | 同一操作の画面記録と問題点 |

正しさの条件は全候補共通。性能は同じWindowsマシン・電源設定・画面条件で1候補ずつ測る。GitHubの別ランナーで得たCPU/メモリを直接順位付けしない。UI画像の「取込」と実画面への「present」を区別し、計測できなかった指標は未測定とする。入力60Hzや表示15Hzは要求した周期と実測した周期の両方を記録する。

機能未実装、試験未実行、環境制約による測定不能、失敗を別の状態にする。共通モックのテストが通っても、各GUIの同じ要件を自動合格にはしない。ダイアログ用の偽物やbackendコマンドの直接呼出だけを、GUI操作テストの成功としない。

## ビルド・配布

共通条件はWindows x64、MSVC、C++23、Release、固定バージョン、ZIP配布、別フォルダーへの展開後起動。3候補ともCMake/Ninjaとvcpkg Manifestを第一候補にする。候補固有のbackend、配布手順、追加ツールが必要な場合は、その管理負担を記録する。

OpenCVはPR #152の `4.12.0#7[contrib]` と同じdefault-features・`x64-windows` を全候補で使う。依存の設定、実際に配布されたDLL、圧縮条件を保存する。候補によって必要なプラグインやレンダラーが違うため、DLL名の一致だけで配布の正しさを判断しない。共通OpenCV以外の画像ライブラリの推移依存も隠さず計上する。

ZIPは既存の `tools/measure_distribution.py` と同じ圧縮条件。外側Artifactと内側配布ZIPは別記録。容量分類はQt専用の規則を流用せず、GUI本体・レンダラー・OpenCV・共有依存・MSVC・OS SDK再配布・文書の所有関係を各候補で確認する。実際に静的リンクが標準となる候補ではexe内の分を含め、独自の動的化を強制しない。

初回のキャッシュなし依存導入とキャッシュ利用時を分け、cache hitだけでなく復元パッケージ数を確認する。Qt Widgetsについても最小配布アプリの数字を共通GUI試作の容量として転用しない。

## 評価の手順

1. Phase 1：全候補のC++23ビルド、固定情報、ライセンス、ZIP配布経路を確認する。資料確認と実測を分離する。
2. Phase 2：3候補すべてで上記の同じGUI仕様を作る。
3. Phase 3：共通の操作シナリオ、データ規模、負荷で正しさと性能を測る。
4. Phase 4：クリーンCIのReleaseビルド・テスト・ZIP展開後起動を行う。
5. Phase 5：下記の同じ仕様変更を行い、保守性を評価して技術選定する。

仕様変更は「ProfileにScenarioごとのenabledを追加し、draft/Apply、Monitorカード、Diagnostics表示、保存前確認、自動テストまで反映する」と先に固定する。変更前commitを全候補で揃え、変更後diff、影響する管理クラス、独自部品、テスト修正、回避策を記録する。これは変更前の初期試作の必須機能には含めない。

保守性・実装量・機能充足を最優先に、テスト性・CI/配布を次、性能を中、容量を低として比較する。行数や容量の自動合計で採用候補を決定しない。フレームワーク固有のアプリコード、宣言UI、独自control、binding/dispatcher/lifetime管理、生成コード、vendored backend、共通コードを分けて数え、生成コードを手書き量へ混ぜない。失敗・未実装・回避策・ライセンス対応の維持作業も記録する。

Phase 5と全候補の共通仕様の評価が終わるまで、採用決定はしない。実装できなかった機能や測定不能な項目がある場合は、そのまま比較表へ残す。

## 現在の証拠

[技術条件の調査](technical-feasibility.md) を参照。`common/` の初版と、`tests/mock_tests.cpp` による標準C++の契約テストを用意した。ローカルのMSVC `19.51.36252.0` / CMake `4.3.1-msvc1` / Ninja `1.13.2` でC++23 ReleaseビルドとCTestに成功した。

Developer PowerShellから、リポジトリルートで次を実行する。

```powershell
cmake -S experiments/gui-comparison -B build/gui-comparison-common -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build/gui-comparison-common
ctest --test-dir build/gui-comparison-common --output-on-failure
```

共通テストは84/10,220ノード、値更新での階層再利用、構造変更時の安定ID、immutable画像、最新状態の採用、60Hz→15Hz取込機会の仮想時計、draft/Apply、長押し、worker停止・再開を検証する。MSVCのサンドボックス内実行ではPDB管理エラーC1902を検出したため、通常のDeveloper PowerShell環境で再実行して成功を確認した。

画像・状態はlatest-only、構造変更コマンドは最大32件を保持し、満杯の場合は呼出元へbusyを返す。workerは制御ロックを短時間だけ保持して要求を取り出し、階層構築と画像生成はロックの外で行う。ProfileEditorはUI所有スレッド専用。3候補のMonitor、Diagnostics、Profile、ダイアログ、長押しResetを実装し、Applyをworker側の設定・階層へ反映する。共通のOpenCV層でPNG、動画入力、GaussianBlur、PHashを実際に実行する。

`.github/workflows/gui-comparison-common.yml` は3候補のWindows Releaseビルド、共通契約、小規模・大量ノードの実GUI契約、配布DLL・通知検証、ZIP生成と展開後GUI契約を検証する。3候補ともクリーンWindows CIとキャッシュ利用CIに成功した。実測値・初回とキャッシュの区別は [比較レポート](results/comparison.md) と [CI記録](results/ci-distribution.json) を参照。

初期試作のローカル配布検証では、3候補とも開発用PATHを除いた配布フォルダーと新規ZIP展開先からのGUI契約に成功した。展開後 / DEFLATE level 6の内側ZIPは、Qt 107,504,644 / 44,268,303 bytes、wxWidgets 25,695,884 / 9,209,868 bytes、Dear ImGui 14,693,027 / 5,480,694 bytes（NDIなし）。変更前の作業ツリーでの実測であり、後続の変更やCIの値は別記録とする。

実GUI契約は各ライブラリのイベント・コントロールAPIをアプリ内から操作する。ImGuiは公開IOへ入力する。実ファイル選択・未保存変更ダイアログの取消も実行する。物理マウス・キーボード、IME、ファイル選択の確定、DPIの実モニター間移動、画面へのpresent遅延は未検証。数秒の混合操作テストのCPU・メモリから性能順位を決めない。スクロールは数値位置の保持を確認し、ノード削除時のアンカー復元は追加評価を要する。

Developer PowerShellで固定baselineのvcpkgを `VCPKG_ROOT` に設定し、候補ごとに次を実行する。既存の配布先・ZIP展開先は上書きせず、新規の出力先を使う。

日本語MSVCではconfigure前からコードページ65001を使用する。ローカルのCMake 4.3.1-msvc1で、それ以外の設定による `/showIncludes` 接頭辞の文字化けとヘッダー依存追跡漏れを実際に検出した。helperはUTF-8、新規configure (`--fresh`)、アプリのclean buildを毎回行い、古いobjectによるABI不整合を避ける。vcpkg binary cacheは利用する。これはGUI候補共通のツールチェーン対応であり、GUIの性能・安定性の差として扱わない。

```powershell
tools/build_gui_comparison.ps1 -Candidate qt
tools/build_gui_comparison.ps1 -Candidate wx
tools/build_gui_comparison.ps1 -Candidate imgui
```

出力は `dist/gui-comparison/<candidate>/`、ZIP・ファイル別レポート・起動ログ・時間は `build/gui-comparison-reports/<candidate>/`。ImGuiは標準portに従い静的リンクし、exe内の分を容量へ含める。各アプリは `--seconds 120 --warmup 30 --page monitor`、`--page diagnostics`、`--large`、`--dark`、`--exercise`、`--report <path>`、`--capture <png>` を受け付ける。計測はGUI取込であり、表示器へのpresentではない。wxWidgetsのnative明暗切替は起動時指定のみで、実行中の切替には再起動が必要。

定常Monitor 30ケース、Diagnostics 6ケース、30分反復6ケースを完了した。[比較レポート](results/comparison.md) に生データ、集計再現手順、メモリ推移、同じ仕様変更による保守性評価、残る未検証事項をまとめる。採用・mainへのマージは未決定。

追加依頼により、**Monitor・Diagnosticsを各180秒×3回**で再測定した。全候補・両データ規模の計36ケースが正常終了。[最新レポート](results/performance-180s-3.md)に中央値・最小最大、CPU・メモリ・入力/取込Hz、Diagnosticsの更新カウンター、配布ファイルのSHA256検証を記録する。上記の旧42ケースと30分反復は保持し、今回の測定とは混ぜない。

同じ配布物を用意した後、既存データを上書きしない新規出力先で実行する。各回30秒warmupを含む計36ケースの所要時間は約126分。CLIの既定条件は旧測定用のままなので、今回の条件を明示する。

```powershell
.venv/Scripts/python.exe tools/run_gui_comparison.py --output build/gui-measurements-new-180s-3 --seconds 180 --repeats 3 --diagnostics-repeats 3 --soak 0
.venv/Scripts/python.exe tools/summarize_gui_comparison.py --source experiments/gui-comparison/results/measurements-180s-3 --output build/gui-performance-180s-3-regenerated.json
```
