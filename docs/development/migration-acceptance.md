## Dear ImGui移行の受け入れ記録（2026-11）

Qt Widgets版の4画面をDear ImGuiへ置き換え、Diagnostics画面は今回の対象外としました。Runtimeの診断データは維持しています。

| 要件 | 確認結果 |
| --- | --- |
| 4画面 | Monitor / Profile / Settings / Aboutを実装。Windows上で起動と画面描画を確認。 |
| Windows標準ファイルピッカー | ProfileのOpen/Save、Scenario YAML、動画ファイルに `IFileOpenDialog` / `IFileSaveDialog` を使用。保存時は `FOS_OVERWRITEPROMPT`。日本語パスはUTF-8で保存し、内部では `std::filesystem::path` へ変換。 |
| draft / saved / applied | ProfileDocumentで分離。SaveはRuntimeを変更せず、Applyはファイルを保存せず、Apply成功だけでは未保存表示を消さない。UIテストで確認。 |
| Core / Runtimeテスト | Debug構成とRelease構成で144/144成功。 |
| Camera / Video / NDIプレビュー | ProfilePreviewのワーカー、Crop/Resize、入力再利用、エラー復旧をUIテストで確認。実機のCamera・外部NDIは手動確認項目として残す。 |
| 日本語IME / DPI / 終了処理 | 日本語フォントを読み込み、Win32のIMEメッセージをImGuiバックエンドへ渡す。WM_DPICHANGEDでスタイルとフォントを再構築。終了時にプレビュー、NDI検索、Session、D3D11、COMを解放。実IME変換と実モニター間移動は手動確認項目。 |
| Windows CI | NDI OFF / ONのmatrixを維持。ImGuiはFetchContentで固定タグを取得し、Qtのインストール手順を削除。 |
| Qt依存の削除 | 製品GUI、CMake、vcpkg manifest、配布ZIPからQtを削除。ZIP検証はQt6Core.dllとplatforms/qwindows.dllを拒否。 |
| 圧縮後ZIP容量 | 同一比較条件（vc_redistなし、DEFLATE level 6）でQt Widgets 44,268,303 bytes、Dear ImGui 6,570,098 bytes（約85.2%削減）。vc_redistを含む実配布ZIPは31,759,381 bytes。CI実測はNDI OFF 31,628,981 bytes、NDI ON 35,301,444 bytes。詳細は[配布](distribution.md#配布zip容量の比較)。 |

ローカルでNDI SDKを用意できないため、NDI ONの実機ループバックはCIと手動確認に委ねます。カメラ・動画・NDIの物理入力、実LiveSplit、実IME、DPIの実画面確認は、自動テストだけで完了扱いにしません。

# C++移行受け入れ記録

[開発ガイド](README.md) · [テスト](testing.md)

旧Pythonアプリケーション、そのテスト、配布ツールは削除済みです。アプリケーションの実装はC++23に統一しました。C++版のビルド・配布に使うPythonの補助スクリプトは残しています。

自動テストで確認した範囲を以下に記録します。接続できなかった外部機器や、提供されていない利用者のシナリオは検証対象に含みません。

## 自動テストで確認した範囲

| 要件 | 確認したテストと内容 |
| --- | --- |
| 暗い画面から明るい画面に変わると、Start／Splitを1回ずつ実行する | `RecordedPipeline.*` は生成したMJPEG録画を実際の入力、正規化、YAMLローダー、インスタンスのワーカーに通し、fake Bridgeの操作履歴を確認します。`TestHost.RecordedVideoThroughYamlToRealBridgeControls` は実際のv4 BridgeでもStart／Splitを確認します。 |
| Split後、外部Undoで同じ区間へ戻って再判定する | `RecordedPipeline.ProfileYamlDecodeTransformStartSplitUndoAndReentry` は録画全体の操作履歴を期待値と比較します。 |
| 自動ResetがSplitに優先し、反応時間を追加で待たない | `ScenarioRuntime.ResetHasPriorityOverSplit` と `InstanceRuntime.AutomaticResetIsEvaluatedDuringReactionWait`。設定した10秒の反応時間より前にResetが届くことを確認します。 |
| 反応待ち中の手動Resetが、未送信のSplitを取り消す | `InstanceRuntime.ManualResetCancelsUnsentSplitWithoutAnotherFrame`。 |
| 通常ActionとResetの確定を別々に待ち、RPC成功時から期限を数える | `ScenarioRuntime.ConfirmationTimeoutStartsAfterRpcSuccess`、Reset拒否、遅れたSplit、Resetの期限切れと、対応するInstanceRuntimeの回帰テスト。 |
| Reset拒否後、タイマーの現在の状態と照合する | InstanceRuntimeでは、Split位置が不変・進行済みの場合、Not runningへの自動Reset、次のフレームでの再判定、Query失敗と再接続を確認します。ScenarioRuntimeでは、現在のPhase・区間のsequenceとOnceの初期化、自動Resetの再判定を確認します。 |
| Pause／Resumeで、保留中のSplitとsequenceの進行を保つ | ScenarioRuntimeとInstanceRuntimeの回帰テスト、および実TestHostのPause／Resumeイベント。 |
| Bridge切断から復旧し、操作結果が不明な場合に二重操作を避ける | 再接続の回帰テストと、通常Action・手動Resetの結果不明時に再送を抑止するテスト。 |
| 判定前にCrop／Resizeする | 録画の常に明るい外枠を切り取り、残った画像をResizeして、暗い画面と明るい画面の操作順を確認します。ローダーとDetectorの既存テストでは、Python版OpenCVによる比較用の期待値も維持します。 |
| 複数のシナリオを独立して実行する | `RecordedPipeline.MultipleYamlScenariosRemainIndependentOnSharedFrames` は、同じデコード済みフレームを使う2つのYAMLシナリオについて、異なる操作履歴を確認します。 |
| Profile JSON v2とYAMLを読み込む | 録画E2EではProfileを保存・再読込してからYAMLを読み込みます。Profileテストはv1からの移行と厳密なv2の保存・読込、ローダーテストは対応するCondition・Detectorと `.py` の拒否を確認します。 |
| Apply前に下書き入力をプレビューする | UIテストは変換後の画素、開いた入力の寸法・FPS、ワーカースレッドでの取得、GUIの応答、入力変更、一時停止した入力、エラーからの復旧、ページの表示・非表示、Session開始前の入力解放を確認します。 |
| NDI SDKで入力を取得する | SDK初期化と、ループバックでの検索・受信・正規化・判定・再接続を確認します。UIテストではSessionを停止し、その送信元を下書きプレビューで受信してからSessionを再開します。 |
| Monitorに判定と処理速度を表示する | UIテストはスコア・しきい値の概要とProcessing FPS列を確認します。Reset Allの長押し・キャンセルの既存テストも維持します。 |

録画テストは、操作履歴と状態が期待どおりかを確認します。そのために、フレームごとの処理完了を待つか、同じ状態が一定時間続く録画を使います。スレッドが毎回まったく同じ時刻に動くことは求めません。

Resetが他の操作と重なる場合や、エラーからの復旧は、既存のRuntimeテストで確認します。同じ検査を、すべての録画テストへ重複して入れる構成にはしていません。

MJPEG録画はOSの動画バックエンドを試す前に、OpenCV内蔵のAVI／MJPEGリーダーで開きます。Windowsの `CAP_ANY` はMedia FoundationやGPUコーデックの検索を先に試すため、短い録画でも、openやStopが遅れたり、デコードに失敗したりする場合があります。

他の形式には引き続き `CAP_ANY` を使います。デコーダーの選択と、非MJPEG入力を別のデコーダーで開く動作は、それぞれ入力ソースの回帰テストで確認します。

CIは録画パイプラインとデコーダーのケースを、NDIの各構成で新しいプロセスから20回実行します。録画処理の5秒、フレームごとの完了待ちの2秒という期限は延長していません。

録画テストが失敗したときは、入力のopen／read／close、フレーム処理の進行、使用したデコーダー、取得・公開フレーム数を報告します。あわせて、Bridgeの操作履歴とQuery、インスタンスのエラー、Scenarioの判定回数、タイマー位置、通常ActionとResetの保留、RuleとCapturePipelineのエラーも出します。

取得スレッドの終了を待って最後のエラーを確認してから、インスタンスのワーカーを止めます。途中のアサーションや終了処理で、フレームの完了待ちに起きた例外が見えなくならないようにするためです。

## 検証の実行方法

[ビルド環境](building.md)を用意し、Developer PowerShellでリポジトリのルートから実行します。

```powershell
cmake --preset full -DDIVERGENCESPLITTER_BUILD_TESTHOST_TESTS=ON
cmake --build --preset full --parallel
ctest --preset full --output-on-failure
# 固定した公式SDKで、SDKとNDIのNDI結合テストを有効にする
cmake --preset full -DDIVERGENCESPLITTER_ENABLE_NDI=ON -DNDI_SDK_DIR=C:/path/to/sdk
cmake --build --preset full --parallel
ctest --preset full --output-on-failure
python tools/run_testhost.py --testhost C:/path/to/TestHost/bin --test-exe build/full/divergencesplitter_testhost_tests.exe --port 54157
```

TestHost用の環境変数がなければ、各制御テストはスキップされます。実際のRPCを確認するときは、上のヘルパーを使ってください。通常のCTestが成功しただけでは、実Bridgeとの通信を検証したことにはなりません。

UIテストはWin32ウィンドウやImGuiコンテキストを作らないため、テスト専用の設定ディレクトリは不要です。

## 利用者の環境で残っている確認

2026-10-30のローカル検証では、Profileのカメラ一覧は空で、外部NDIの検索でも送信元は見つかりませんでした。既定のアプリデータフォルダーには、保存済みProfileとSettingsがありませんでした。稼働中の本番LiveSplitや利用者のシナリオも確認できていません。隔離したTestHostとNDIループバックは利用でき、テスト済みです。

- [ ] 実際に使う各JSON ProfileをC++版で読み込み、**別の新しいファイル**に保存して再読込する。
- [ ] 使用するYAMLと参照画像を代表的な映像で確認し、スコアのしきい値と画像変換の範囲を調べる。
- [ ] 使用中のPython `.py` シナリオをYAMLに書き直し、同じ録画で操作履歴を比較する。C++版はPythonモジュールを実行しない。
- [ ] 実際のCameraモードをProfileで選び、開いた入力の寸法・FPS、Crop／Resize、ページの非表示・再表示、プレビュー後のApplyを確認する。
- [ ] 実際の外部NDI送信元を検索・受信し、送信の一時停止・再起動、下書きの編集、Sessionの映像取得への切り替えを確認する。
- [ ] 実際のLiveSplitとBridge v4でテスト用Runを使い、Start／Split／Undo／Resetと切断・再接続を確認する。

上の項目は、利用者の実環境でC++版を使う前に、まだ確認が必要な作業です。旧実装を削除したことで完了した扱いにはしません。自動テストも、これらの実環境での確認を代わりに済ませるものではありません。