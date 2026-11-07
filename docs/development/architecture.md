# アーキテクチャ

[開発ガイド](README.md)

## コンポーネントの構成

CMakeプロジェクトのルートはリポジトリ直下です。実装は `src/` に置き、CoreやRuntimeなど複数のターゲットが使うヘッダーは `include/divergencesplitter/` に置きます。

`include/` にあるヘッダーを、外部向けに互換性を保証するAPIとして扱っているわけではありません。公開SDKを提供する場合、その時点で公開対象を決めます。GUIの内部ヘッダーは実装と同じ `src/ui/` に置き、UIターゲットとUIテストだけから参照します。

`src/core/` にはDetector、Condition、Rule、Scenario、画像変換、UTF-8パス変換を置きます。`src/capture/` は映像入力とCapturePipeline、`src/runtime/` はBridge連携、Scenario実行、Session、設定、ログの実装です。

ソースのディレクトリとCMakeターゲットは、必ずしも1対1には対応しません。CaptureのソースはRuntimeライブラリに含め、画像の正規化はCoreに含めています。

テストソースと共通の補助コードは `tests/` にまとめ、動画素材は `tests/data/` に置きます。録画回帰やNDI結合の分類にはCTestのラベルを使います。

| CMakeファイル | 責務 |
| --- | --- |
| [CMakeLists.txt](../../CMakeLists.txt) | Project、オプション、依存関係の発見、Dear ImGuiのFetchContent、ルートでのテスト有効化、サブディレクトリ登録。 |
| [src/CMakeLists.txt](../../src/CMakeLists.txt) | Core・Runtime・CLI・Dear ImGui・UIターゲット。 |
| [tests/CMakeLists.txt](../../tests/CMakeLists.txt) | GoogleTest、UI、NDI、TestHostのテスト登録。 |
| [cmake/Packaging.cmake](../../cmake/Packaging.cmake) | インストール、依存ライセンス収集、Windows ZIPとCPack。 |

```text
Camera / Video / NDI
        |
  CapturePipeline thread
        |
  FrameNormalizer (Crop -> Resize)
        |
  shared newest frame + per-frame cache ----> Monitor preview
        |
        +----> InstanceRuntime 0 ----> ScenarioRuntime ----> Bridge client 0
        +----> InstanceRuntime 1 ----> ScenarioRuntime ----> Bridge client 1
                    |                     |
                    +------ diagnostics --+----> Dear ImGui UI
```

| コンポーネント | 役割・実装 |
| --- | --- |
| Capture | [src/capture/](../../src/capture)：デバイス・モードの列挙、入力の所有、動画の再生間隔、NDIの変換・検索、取得スレッド。 |
| Normalizer | [frame_normalizer.cpp](../../src/core/frame_normalizer.cpp)：Crop・Resizeを検証し、全インスタンス向けの正規化フレームを生成。 |
| Scenario（core） | [src/core/](../../src/core)：YAML、参照画像、Detectorスコア、Conditionツリー、Rule、RuleSequence。GUIやネットワークRPCは含まない。 |
| ScenarioRuntime | [scenario_runtime.cpp](../../src/runtime/scenario_runtime.cpp)：確定したタイマー状態からのRule選択、リセット、保留Action、診断ツリー。 |
| InstanceRuntime | [instance_runtime.cpp](../../src/runtime/instance_runtime.cpp)：シナリオ・Bridge接続ごとのワーカー、フレーム受信、イベント、反応時間、操作送信、再接続、診断。 |
| Session・configuration | [session.cpp](../../src/runtime/session.cpp)、[configuration.cpp](../../src/runtime/configuration.cpp)：JSON、入力の作成、任意の参照Resize、Sessionの置き換えと停止。 |
| Bridge | [livesplit_client.cpp](../../src/runtime/livesplit_client.cpp)、[livesplit_adapter.cpp](../../src/runtime/livesplit_adapter.cpp)：クライアントとの型変換、Query・Eventによる同期、ローカルの状態とRunリビジョン。 |
| GUI | [src/ui/](../../src/ui)：Dear ImGui、Win32ウィンドウ、Direct3D 11、AppController、ProfileDocument。タイマーRPCはGUIスレッドで待たない。 |
| CLI | [src/cli/main.cpp](../../src/cli/main.cpp)：Profile・シナリオの検証、時間指定のSession、NDIの初期化・検索確認。 |

## フレームと所有関係

CaptureはCrop・Resize後の画像、取得時刻、判定用の単調増加時刻、フレーム単位のキャッシュを、`shared_ptr<SharedFrameEvaluation>` で全インスタンスへ渡します。各インスタンスが次の判定用に保持するのは、最新の1フレームだけです。新しいフレームが来ると古いフレームを置き換えるため、未処理のフレームが無制限に増えることはありません。

そのため判定が遅れると、短時間だけ映った場面を見落とす場合があります。映像の取得FPSと判定回数が一致するとは限りません。

同じフレームを複数のシナリオで使うとき、同等のDetectorの計算結果やグレースケール・hashの前処理はキャッシュで共有します。キーには、型、ROI、オプション、参照画像の内容を含めます。

Conditionの時計、edgeの履歴、カウンター、sequenceの位置は、このキャッシュでは共有しません。シナリオを読み込むたびに、個別に初期化します。プレビューには画像のコピーを渡すため、入力側の一時バッファーがなくなっても表示できます。

OpenCVはWindowsの非ASCIIパスを直接扱えないため、動画入力ではASCII短縮パスまたは一時ハードリンクを試し、最後にACPへフォールバックします。

NDIにはインターリース済みのBGRX・BGRAを要求します。UYVY・UYVAとRGBA・RGBXの変換にも対応し、行ストライドに従って読み取り、alphaを取り除いたBGR画像をアプリ側で保持します。readで待つのは最大50msです。通常のタイムアウトでは、受信機を作り直しません。

NDI Runtimeは配布ZIPに同梱せず、起動時にインストール済みRuntimeを検出します。NDILIB_REDIST_FOLDERとNDILIB_LIBRARY_NAME、一般的なインストール先を確認し、LoadLibraryExW、NDIlib_v5_load、初期化の成功を調べます。Runtimeがない場合や初期化に失敗した場合も、Camera・Video入力とアプリ本体は通常どおり動作し、NDI入力だけを無効にします。NDI SDKヘッダーはビルド用に `third_party/ndi/include` へ固定版を同梱し、NDIのインポートライブラリにはリンクしません。

## Conditionの評価

`all` と `any` はYAMLに書かれた順に子の条件を評価します。結果が決まった後も残りの子を呼び出しますが、短絡モードを持ちます。

短絡モードでの動作は型によって異なります。`detected` はDetectorを実行せず、スコアも更新しません。`all`、`any`、`not` は、同じモードを子へ渡します。edge、`once`、`hold`、`nth` は子を通常評価して記録を更新し、`elapsed` も計測を進めます。ただし、完了済みの `once` と `nth` は子を実行せず、表示用の状態をskippedにします。

`reset_when` は短絡モードでもReset条件を通常評価します。必要なら両方の子をリセットし、その後で主条件に短絡モードを渡します。`then` は現在のステップだけを通常評価し、進行と完了の記録を更新します。

短絡モードでは、各Conditionは親へ真偽値を返しません。このため、一部の記録が進んでも、条件を組み合わせた全体が成立するとは限りません。

`mark_skipped` は子を実行せず、表示用の状態だけを再帰的に変えます。`then` の現在以外のステップや、完了済みのConditionの子に使われます。また、Actionが決まった後のRuleや現在のPhase・区間に対応しないグループは、通常の判定対象にしません。利用者向けの説明は[Conditionリファレンス](../scenarios/conditions.md)を参照してください。

## Bridgeとタイマー制御

固定バージョンの `livesplit-bridge-client-cpp` が、Protocol v4の通信と通信ワーカーを担当します。`LiveSplitBridgeClient` はライブラリから得たスナップショットとエラーを、アプリ側の型に変換します。

操作の送信には非同期APIを使い、インスタンスのスレッドで完了を待ちます。GUIや画像取得のスレッドではRPCを待ちません。Reaction timeは、原因となったフレームの取得時刻を基準にします。

`LiveSplitBridgeAdapter` は、初期接続時のQueryでタイマー情報を取得し、Session・状態・Runのリビジョンを追跡します。必要な情報がそろったタイマーイベントやResetイベントでは、毎回Run全体を取り直さず、イベントを反映します。

イベントの情報が足りない場合、SessionやRunが変わった場合、破棄されたイベント数が増えた場合は、同期し直します。ScenarioRuntimeは古いリビジョンを受け付けません。別のSessionを受け入れる前にも、再同期が必要です。

InstanceRuntimeは送信予定のActionと実行予定時刻を記録します。実行予定時刻は、フレームの取得時刻にReaction timeを加えた時刻です。待機中も、Bridgeイベント、新しいフレーム、手動Resetを処理します。

送信直前に状態を確認し直し、該当する保留操作や制御状態が変わっていれば、そのActionを取り消します。関係のないイベントや、内容が変わらないQueryでは待機を続けます。手動Resetと、通常Actionの反応待機に割り込む自動Resetは、追加の遅延を置かず、未送信の通常Actionを取り消します。

RPCに成功したら、`action_accepted` に単調増加時刻を渡し、通常ActionとResetそれぞれの確定待機を始めます。成功直後に必要Queryするわけではありません。BridgeイベントをAdapterへ反映し、対応する状態変化を待ちます。待機の選択と解除条件は[YAMLリファレンス](../scenarios/yaml-reference.md#actionの保留と確定待ち)を参照してください。

InstanceRuntimeは、フレームが来なくても期限を調べます。1秒経ったらQueryし、`state_wait_timed_out` で未確定の保留と対応するRuleの状態を解除します。Queryに失敗した場合は例外を処理して再接続・再同期へ進み、状態を確認できるまで新しいフレームを評価しません。

通常Actionを送れなかった場合や拒否された場合は、`action_not_dispatched` で対応するグループを初期化します。Resetの保留は通常Actionと別に持つため、送信前のResetを取り消しても、送信済みの通常Actionの確定待機は残ります。

ResetのRPCが拒否された場合は、Queryした後、`settle_rejected_reset` で両方の旧保留を解除します。同時に、Resetグループと現在のPhase・区間のグループを初期化します。次の判定は後のフレームで行います。GUIからの手動Resetも、直接RPCを送らず、インスタンスのスレッドへ要求を渡して処理します。

`control_result_unknown` の場合は、その操作を無条件には再送しません。ScenarioRuntimeを破棄して再接続・再同期し、同じ確定スナップショットに対する同じ自動操作を抑止します。応答が失われただけで、実際には成功している操作を、二重に実行することを避けるためです。

## SessionとGUIの寿命

Applyでは、新しいシナリオ、入力、インスタンスを構築してから、実行中のSessionを置き換えます。入力を実際に開くのは取得開始後の非同期処理なので、Applyが成功しても、まだフレームが届くとは限りません。

終了時は、まず映像取得を止めます。次に全インスタンスを停止し、クライアントを閉じてから、受信先のインスタンスを破棄します。参照画像のResizeは入力映像の正規化とは別で、シナリオ読み込み時に行います。

GUIの状態は次の3つを区別します。

- **draft**: Profile画面で直接編集している値。
- **saved**: 最後に読み込んだ、または保存したProfileファイルの値。
- **applied**: 現在Runtimeへ適用されている値。AppControllerが所有します。

SaveはRuntimeを変更しません。Applyはファイルを保存しません。Applyが成功しても、draftとsavedが一致するまで未保存表示は消えません。失敗・キャンセルではdraftを破棄しません。Openは読み込んだProfileをRuntimeへ適用し、draftとsavedをその内容に置き換えます。

Monitorの更新周期は100msです。Profileのプレビューも約100msで更新します。Diagnostics画面は今回実装していませんが、Runtimeの診断スナップショットは維持しています。Monitorはそのスナップショットから、現在のCondition、しきい値、スコアの概要を表示します。

NDI検索はGUIスレッドの外で行い、保存済みの名前がオフラインでも下書きから消えないようにします。Monitorのプレビュー画像は、実行中のRuntimeから取得します。

[ProfilePreview](../../src/ui/profile_preview.cpp)は、Sessionとは別のワーカーで入力を保持し、取得、正規化、OpenCVのMatへの変換を行います。GUIは最新の画像をD3D11テクスチャへ転送し、約10Hzで表示します。

入力が同じかを判断するときは、Crop・Resizeなどの変換設定を除いて比較します。そのため、変換だけの変更で入力を開き直す必要はありません。最後のフレームを保持するので、送信元が一時停止していても変換結果を更新できます。

入力を変える場合は、前の入力を閉じてから新しい入力を開きます。ページを隠す、プレビューを無効にする、Sessionを開始する操作では、プレビューが保持する入力を閉じます。Sessionを始める前にプレビューを止め、同じ入力を二重に開くことを避けます。

Monitorはインスタンスの世代と評価回数からProcessing FPSを計算します。診断スナップショットから、現在のCondition、しきい値、スコアの概要も作ります。Conditionツリー全体と最大スコアは、Diagnostics画面の代わりにRuntimeの診断データとして保持します。

fakeと実接続の検証範囲は[テスト](testing.md)、ターゲットと依存関係は[ビルド](building.md)を参照してください。
