# テスト

[開発ガイド](README.md) · [ビルド環境](building.md)

## CTest

対応するプリセットを設定した後、リポジトリのルートで実行します。

```powershell
cmake --build --preset full --parallel
ctest --preset full --output-on-failure
ctest --preset full -N
ctest --preset full -R 'Conditions|ScenarioLoader|ScenarioRuntime' --output-on-failure
```

ビルドした構成に合わせて、`core`、`core-release`、`full-release` も使えます。coreにはQtテストを含まず、NDIの既定値はOFFです。

CMakeはGoogleTestの各ケースと、Qtテストの実行ファイルをCTestへ登録します。Qtテストを実行するときは、CTestがoffscreen表示と、必要なプラグイン・DLLのパスを設定します。

| 分野 | 主なテストと確認対象 |
| --- | --- |
| Detector | [detector_tests.cpp](../../tests/detector_tests.cpp)：計算式、alphaマスク、寸法・チャンネル制約、hash、histogram、相関。 |
| Condition | [condition_tests.cpp](../../tests/condition_tests.cpp)：短絡順序、edge履歴、elapsedの開始、Holdの連続成立、Once／Nth、Thenの進行・リセット。 |
| YAML | [scenario_loader_tests.cpp](../../tests/scenario_loader_tests.cpp)：スキーマエラー、アンカー・単一／複数マージと優先順位、循環参照、null・数値境界、UTF-8パス、ROI、参照変換。UIテストでは不正YAMLからの復帰も確認します。 |
| Profile | [profile_tests.cpp](../../tests/profile_tests.cpp)：JSON項目、入力型、設定、保存形式。 |
| Capture | [camera_tests.cpp](../../tests/camera_tests.cpp)、[normalizer_tests.cpp](../../tests/normalizer_tests.cpp)、[ndi_tests.cpp](../../tests/ndi_tests.cpp)：機器の特定、画像変換、fake NDIの寿命・形式・タイムアウト・復帰。 |
| キャッシュ・Runtime | [frame_cache_tests.cpp](../../tests/frame_cache_tests.cpp)、[scenario_runtime_tests.cpp](../../tests/scenario_runtime_tests.cpp)、[instance_runtime_tests.cpp](../../tests/instance_runtime_tests.cpp)：共有評価、Phase選択、リセット、fake Bridge送信、反応時間中の自動・手動Reset、通常ActionとResetの別々の確定待ち、遅延イベント、入力停止中の期限切れ、Reset拒否後のQuery、再接続・結果不明時の処理。 |
| UI・ログ | [ui_tests.cpp](../../tests/ui_tests.cpp)、[logging_tests.cpp](../../tests/logging_tests.cpp)：下書きプレビューの入力排他・非表示時の解放・一時停止入力の変換・エラー復旧、参照検証、検索・プレビュー中の応答性、MonitorのCondition概要、Reset Allの長押し・中断、Widget、ログのローテーション。 |

fakeを使うテストは実機の代わりに決めた入力や応答を与え、同じ条件を再現してアプリの動作を調べます。物理カメラ、外部のNDI送信元、利用者のLiveSplitで動くことを確認するテストとは別です。

## 録画を使うE2Eテスト

[recorded_pipeline_tests.cpp](../../tests/recorded_pipeline_tests.cpp)は、録画の読み込みからタイマー操作の要求までを通して調べるE2Eテストです。MJPEG AVI、Profile JSON、YAMLを生成し、デコード、Crop／Resize、CapturePipeline、Scenarioの判定、InstanceRuntimeを実際に動かして、fake Bridgeに届いた操作履歴を確認します。

確認するのは、Start／Split、外部Undoで戻った区間の再判定、同じフレームを使う複数シナリオの独立した動作です。フレームごとに処理が終わるのを待って入力順と操作履歴を比べるため、通常の速度制限なしの映像取得を再現する試験ではありません。

VideoFileSourceでは、内蔵MJPEGデコーダーを先に使うことと、H.264の動画をWindowsのデコーダーで読み込めることを確認します。RecordedPipelineでは、低FPSの動画でも速やかに停止できるかを確認します。

CTestの `recorded_pipeline_repeat` は、録画とデコーダーのケースを新しいプロセスで20回実行します。毎回起動し直すことで、デコーダー起動時の不安定さも調べます。

```powershell
ctest --preset full -R 'RecordedPipeline|VideoFileSource|recorded_pipeline_repeat' --output-on-failure
```

実Bridgeへの送信まで含む録画テストは次のTestHost構成で実行します。

## 実LiveSplit.Bridge TestHostとの結合

TestHost用のテスト実行ファイルは、次のオプションで追加します。

```powershell
cmake --preset full -DDIVERGENCESPLITTER_BUILD_TESTHOST_TESTS=ON
cmake --build --preset full --parallel
```

[cpp23.yml](../../.github/workflows/cpp23.yml) と同じ固定リビジョンのBridge TestHostを別のディレクトリでビルドします。Gitと.NET SDK 10を使ってください。Bridgeリポジトリ側のビルド要件も満たす必要があります。

```powershell
git clone --recurse-submodules https://github.com/Nanahuse/LiveSplit.Bridge.git C:/src/LiveSplit.Bridge-TestHost
git -C C:/src/LiveSplit.Bridge-TestHost checkout 4c14c0161eacd50b05411c0d20f5eff523e9c155
git -C C:/src/LiveSplit.Bridge-TestHost submodule update --init --recursive
dotnet build C:/src/LiveSplit.Bridge-TestHost/tests/LiveSplit.Bridge.TestHost/LiveSplit.Bridge.TestHost.csproj --configuration Release
```

リポジトリのルートに戻り、未使用のローカルポートで既存ランナーを実行します。

```powershell
python tools/run_testhost.py --testhost C:/src/LiveSplit.Bridge-TestHost/tests/LiveSplit.Bridge.TestHost/bin --test-exe build/full/divergencesplitter_testhost_tests.exe --port 54157
```

ヘルパーはTestHostを起動し、標準入力を開いたままREADYの出力を待ちます。続いて `DIVERGENCESPLITTER_TESTHOST_PORT` と `DIVERGENCESPLITTER_TESTHOST_ALLOW_CONTROL=1` を設定してテストを実行し、最後にTestHostを止めます。

テストではQuery・EventとPause／Resumeを確認します。`TestHost.RecordedVideoThroughYamlToRealBridgeControls` は、録画をYAMLで判定し、実BridgeへStart／Splitを送ります。操作数、最後のSplitの成功、実タイマーのSplit位置1、動画の終端を確認します。

制御テストはTestHostの既定の2区間Runを必要とし、タイマーの開始・Split・Resetも行います。隔離したTestHostを使い、本番LiveSplitのポートには接続しないでください。

自分でTestHostを起動する場合は、CTestの前に `DIVERGENCESPLITTER_TESTHOST_PORT` を設定してください。未設定のままではテストをスキップするため、CTestが成功しても実Bridgeを制御できたことにはなりません。制御テストには `DIVERGENCESPLITTER_TESTHOST_ALLOW_CONTROL=1` も必要です。

ヘルパーの `--testhost` にディレクトリを渡す場合は、その中にTestHostの実行ファイルが1つだけ存在する必要があります。

## 実NDIの検証

固定SDKでNDIを有効にした構成で実行します。

```powershell
ctest --preset full-release -R '^ndi_sdk_' --output-on-failure
$env:NDI_SOAK_SECONDS = '600'
.\build\full-release\divergencesplitter_ndi_loopback_tests.exe
Remove-Item Env:NDI_SOAK_SECONDS
```

`ndi_sdk_initialization` はSDKの初期化と終了を確認します。`ndi_sdk_loopback` は、実SDKでローカルの送信元を作り、検索、選択、受信、BGR変換、Crop／Resize、プレビュー、ScenarioのStart判定を確認します。さらに送信元を破棄して作り直し、再接続と終了も調べます。

継続時間は最大3600秒にできます。ただし、CTestのタイムアウトは90秒なので、長時間試す場合は、上の例のようにテストの実行ファイルを直接呼んでください。

[NDI Tools](https://ndi.video/tools/) などの独立した送信元でも対象ネットワークを確認してください。選択、プレビュー、判定、停止・再開後の復帰、保存Profileの再読込、継続受信を調べます。送受信側のバージョン、時間、フレーム数、エラー、ネットワーク構成を記録してください。ローカルループバックだけでは別の送信元・ネットワークを検証できません。

## 配布ヘルパー

```powershell
python -m unittest discover -s tools/tests -v
```

SDK取得とZIP検証ヘルパーを検査します。実際のZIPは[配布手順](distribution.md)で別途確認してください。

## ドキュメントの例の検証

[profile.example.json](../../examples/profile.example.json) の動画・シナリオの絶対パスを変更し、ビルドしたCLIの `--profile <path> --check` を実行します。実際のC++ローダーでProfileとシナリオ、参照Resizeを確認し、タイマー操作は送りません。

[シナリオ例](../scenarios/examples.md)のYAMLも、参照画像と一緒に保存し、Profileの参照先を変えて確認してください。ConditionやDetectorだけを示した例は、それだけではシナリオとして読み込めません。完全なシナリオの中に埋め込んで試します。

JSONやYAMLの文法として正しいだけでは、アプリの設定として有効とは限りません。また、`--check` は動画やコーデックを開かず、映像とDetectorの寸法も比べません。それらはMonitorで実際の映像を表示するか、フレームを使うテストで確認してください。

ソースへのパスとMarkdownアンカーを確認し、`git diff --check` と `git diff --name-only` で文書・例だけの変更であることも確認します。
