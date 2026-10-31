# アーキテクチャ

[日本語（正本）](architecture.md) | [English](architecture.en.md)

[開発ガイド](README.md)

## コンポーネントの構成

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
                    +------ diagnostics --+----> Qt GUI
```

| コンポーネント | 役割・実装 |
| --- | --- |
| Capture | [src/capture/](../../src/capture)：デバイス・モードの列挙、入力の所有、動画の再生間隔、NDIの変換・検索、取得スレッド。 |
| Normalizer | [frame_normalizer.cpp](../../src/core/frame_normalizer.cpp)：Crop／Resizeを検証し、全インスタンス向けの正規化フレームを生成。 |
| Scenario／core | [src/core/](../../src/core)：YAML、参照画像、Detectorスコア、Conditionツリー、Rule、RuleSequence。GUIやネットワークRPCは含まない。 |
| ScenarioRuntime | [scenario_runtime.cpp](../../src/runtime/scenario_runtime.cpp)：確定したタイマー状態からのRule選択、リセット、保留Action、診断ツリー。 |
| InstanceRuntime | [instance_runtime.cpp](../../src/runtime/instance_runtime.cpp)：シナリオ・Bridge接続ごとのワーカー、フレーム受信、イベント、反応待ち、操作送信、再接続、診断。 |
| Session／configuration | [session.cpp](../../src/runtime/session.cpp)、[configuration.cpp](../../src/runtime/configuration.cpp)：JSON、入力の作成、任意の参照Resize、Sessionの置き換えと停止。 |
| Bridge | [livesplit_client.cpp](../../src/runtime/livesplit_client.cpp)、[livesplit_adapter.cpp](../../src/runtime/livesplit_adapter.cpp)：クライアントとの型変換、Query・Eventによる同期、ローカルの状態・Runリビジョン。 |
| GUI | [src/ui/](../../src/ui)：Qt Widgetsの画面とAppController。下書きとスナップショットを扱い、タイマーRPCはGUIスレッドで待たない。 |
| CLI | [src/cli/main.cpp](../../src/cli/main.cpp)：Profile・シナリオの検証、時間指定のSession、NDIの初期化・検索確認。 |

## フレームと所有関係

Captureは正規化した画像、取得時刻、評価用の単調増加時刻、フレーム単位の共有キャッシュを `shared_ptr<SharedFrameEvaluation>` として公開します。各インスタンスは最新の待機フレームだけを保持します。古いフレームを置き換えるため、処理待ちのフレームは無制限には蓄積しません。評価が遅いと短時間の表示を見落とす場合があり、取得FPSと評価回数は一致するとは限りません。

同じフレームのキャッシュで、同等のDetector結果とグレースケール・hashの前処理を共有します。キーには型、ROI、オプション、参照内容を含みます。Conditionの状態は別で、シナリオを読み込むたびに時計、edgeの履歴、カウンター、sequenceの位置を個別に作ります。プレビューはコピーを保持するため、入力の一時バッファーの寿命には依存しません。

NDIはデインターレースしたBGRX／BGRAを要求します。変換はUYVY／UYVAとRGBA／RGBXにも対応し、行ストライドを守り、alphaを除き、BGRバッファーを所有します。readの待機は最大50msで、通常のタイムアウトなら受信機を保持します。SDKは実行ファイルのディレクトリから動的に読み、作業ディレクトリやPATHへはフォールバックしません。NDIのインポートライブラリにはリンクしません。SDK無効ビルドも同じ公開Capture APIを使います。

## Bridgeとタイマー制御

固定した `livesplit-bridge-client-cpp` がProtocol v4の通信とワーカーを管理します。`LiveSplitBridgeClient` はそのスナップショットとエラーをアプリの型へ変換します。操作はライブラリの非同期APIを使い、インスタンスのスレッドで完了を待ちます。GUIと取得スレッドはRPCを待ちません。Reaction timeの基準はフレーム取得時刻です。

`LiveSplitBridgeAdapter` はQueryで初期接続し、Session・状態・Runのリビジョンを追跡します。情報がそろったタイマー・Resetイベントは毎回Run全体をQueryせず反映します。状態情報が不足したイベント、SessionやRunの変更、破棄されたイベント数の増加では同期します。ScenarioRuntimeは古いリビジョンを拒否し、異なるSessionを受け入れる前に再同期を必要とします。

操作成功後は確定状態をQueryし、遷移更新をScenarioRuntimeへ渡します。拒否・未送信時は対応グループをリセットして再評価できます。`control_result_unknown` は無条件には再送しません。ScenarioRuntimeを破棄して再接続・再同期し、同じ確定スナップショットに対する同じ自動操作を抑止します。応答喪失時の二重操作を防ぐための動作です。

ScenarioRuntimeの保留Actionには、フレーム評価で確認する1秒のタイムアウトもあります。通信応答のタイムアウトとは別です。公開Ruleの選択とリセットは[YAMLリファレンス](../scenarios/yaml-reference.md)に集約しています。手動ResetもGUIから直接RPCを送らず、要求をキューに入れてインスタンスのスレッドで現在の状態を使って処理します。

## SessionとGUIの寿命

Applyは新しいシナリオ、入力、インスタンスを構築してから旧Sessionを置き換えます。入力のopenは取得開始後に非同期で行うため、Apply成功だけではフレーム到着を保証しません。終了時は入力取得を止めた後、各インスタンスを停止してクライアントを閉じ、受信先のインスタンスを破棄します。参照Resizeは入力正規化とは別に、シナリオの読み込み時に行います。

AppControllerは適用済みProfile、ファイルパス、Settingsを区別し、ProfilePageが下書きを持ちます。Monitorは100ms周期で更新し、Diagnosticsは表示中に300ms周期で更新します。NDI検索はGUIスレッド外で行い、オフラインの下書き名を保ちます。Monitorのプレビューは実行中のRuntimeから取得します。

fakeと実接続の検証範囲は[テスト](testing.md)、ターゲットと依存関係は[ビルド](building.md)を参照してください。
