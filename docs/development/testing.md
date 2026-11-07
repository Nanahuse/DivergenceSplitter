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

ビルドした構成に合わせて、`core`、`core-release`、`full-release` も使えます。coreにはUIテストを含みません。NDI Runtimeがない環境ではNDIループバックテストをスキップします。

CMakeはGoogleTestの各ケースをCTestへ登録します。UIテストはDear ImGuiの描画やWin32ウィンドウを作らず、UIから分離した状態管理・Monitorモデル・入力プレビューを検証します。

| 分類 | 主なテストと確認対象 |
| --- | --- |
| Detector | [detector_tests.cpp](../../tests/detector_tests.cpp)：計算式、alphaマスク、寸法・チャンネル制約、hash、histogram、相関。 |
| Condition | [condition_tests.cpp](../../tests/condition_tests.cpp)：短絡評価、edge履歴、elapsedの開始、Holdの連続成立、Once・Nth、Thenの進行とリセット。 |
| YAML | [scenario_loader_tests.cpp](../../tests/scenario_loader_tests.cpp)：スキーマエラー、アンカー・単一・複数マージと優先順、循環参照、null・数値境界、UTF-8パス、ROI、参照変換。 |
| Profile | [profile_tests.cpp](../../tests/profile_tests.cpp)：JSON評価、入力型、設定、保存形式。 |
| Capture | [camera_tests.cpp](../../tests/camera_tests.cpp)、[normalizer_tests.cpp](../../tests/normalizer_tests.cpp)、[ndi_tests.cpp](../../tests/ndi_tests.cpp)：機器の特定、画像変換、fake NDIの寿命・形式・タイムアウト・復帰。 |
| キャッシュ・Runtime | [frame_cache_tests.cpp](../../tests/frame_cache_tests.cpp)、[scenario_runtime_tests.cpp](../../tests/scenario_runtime_tests.cpp)、[instance_runtime_tests.cpp](../../tests/instance_runtime_tests.cpp)：共有評価、Phase選択、リセット、fake Bridge送信、反応時間中の自動・手動Reset、通常ActionとResetの別、未確定確認、遅延イベント、入力停止中の期限処理、Reset拒否後のQuery、再接続と結果不明時の処理。 |
| UI・ログ | [ui_model_tests.cpp](../../tests/ui_model_tests.cpp)、[logging_tests.cpp](../../tests/logging_tests.cpp)：draft/saved/appliedの分離、MonitorのCondition概要、Reset Allの長押し、プレビューの入力排他・変換・エラー復旧、UTF-8パス、ログのローテーション。 |

fakeを使うテストは実機の代わりに決めた入力や応答を与え、同じ条件を再現してアプリの動作を調べます。物理的なカメラ、外部のNDI送信元、利用者のLiveSplitで動くことを確認するテストとは別です。

GUIの起動確認は、ビルドした実行ファイルに `--smoke-test` を渡します。実際のWin32ウィンドウとDirect3D 11の初期化、NDI Runtimeがある場合の初期化を確認し、約20フレームで終了します。NDI Runtimeがない場合も起動できることを確認します。画面の見た目やIMEの変換操作は、この自動試験だけでは確認できません。

## 録画を使ったE2Eテスト

[recorded_pipeline_tests.cpp](../../tests/recorded_pipeline_tests.cpp)は、録画の読み込みからタイマー操作の要求までを通して調べるE2Eテストです。JPEG AVI、Profile JSON、YAMLを生成し、デコード、Crop・Resize、CapturePipeline、Scenarioの判定、InstanceRuntimeを実際に動かして、fake Bridgeに届いた操作履歴を確認します。

確認するのは、Start・Split、外部Undoで戻った区間の再判定、同じフレームを使う複数シナリオの独立した動作です。フレームごとに処理が終わるのを待って入力順と操作履歴を比べるため、通常の速度制限なしの映像取得を再現する試験ではありません。

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

[cpp23.yml](../../.github/workflows/cpp23.yml) と同じ固定リビジョンのBridge TestHostを別のディレクトリでビルドします。gitと.NET SDK 10を使ってください。Bridgeリポジトリ側のビルド要件も満たす必要があります。

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

ヘルパーはTestHostを起動し、標準出力を開いたままREADYの出力を待ちます。続いて `DIVERGENCESPLITTER_TESTHOST_PORT` と `DIVERGENCESPLITTER_TESTHOST_ALLOW_CONTROL=1` を設定してテストを実行し、最後にTestHostを止めます。

テストではQuery・EventとPause・Resumeを確認します。`TestHost.RecordedVideoThroughYamlToRealBridgeControls` は、録画をYAMLで判定し、実BridgeへStart・Splitを送ります。操作数、最後のSplitの成功、実タイマーのSplit位置1、動画の終端を確認します。

制御テストはTestHostの既定の2区間Runを必要とし、タイマーの開始・Split・Resetも行います。隔離したTestHostを使い、本番LiveSplitのポートには接続しないでください。

自分でTestHostを起動する場合、CTestの前に `DIVERGENCESPLITTER_TESTHOST_PORT` を設定してください。未設定のままではテストをスキップするため、CTestが成功しても実Bridgeを制御できたことにはなりません。制御テストには `DIVERGENCESPLITTER_TESTHOST_ALLOW_CONTROL=1` も必要です。

ヘルパーの `--testhost` にディレクトリを渡す場合、その中にTestHostの実行ファイルが1つだけ存在する必要があります。

## 実NDIの検証

NDI Runtimeを別途インストールして実行します。Runtimeが見つからない場合、`ndi_sdk_loopback` はスキップされます。NDIの初期化・受信を確認するときは、Runtimeのフォルダーを `NDI_RUNTIME_DIR_V6` に指定してください。

```powershell
$env:NDI_RUNTIME_DIR_V6 = 'C:/path/to/NDI Runtime'
ctest --preset full-release -R '^ndi_sdk_loopback$' --output-on-failure
$env:NDI_SOAK_SECONDS = '600'
.\build\full-release\divergencesplitter_ndi_loopback_tests.exe
Remove-Item Env:NDI_SOAK_SECONDS
Remove-Item Env:NDI_RUNTIME_DIR_V6
```

`ndi_sdk_loopback` は、実Runtimeでローカルの送信元を作り、検索、選択、受信、BGR変換、Crop・Resize、プレビュー、ScenarioのStart判定を確認します。さらに送信元を破棄して作り直し、再接続と終了を調べます。

継続時間は最大3600秒にできます。ただし、CTestのタイムアウトは90秒なので、長時間試す場合は上記のようにテストの実行ファイルを直接呼んでください。

Runtimeをインストールしていない環境でも、`DivergenceSplitter.exe --smoke-test` とCamera・Videoのテストは実行できます。`--smoke-test` はMonitorに続いてAboutを描画し、ライセンス表の読み込みも確認します。NDI Runtimeがない状態でNDI入力を選んだ場合は、ProfileのNDI入力設定にインストール案内が表示され、NDI入力だけが利用不可になります。

[NDI Tools](https://ndi.video/tools/) などの独立した送信元も対象ネットワークに確認してください。選択、プレビュー、判定、停止・再開後の復帰、保存Profileの再読込、継続受信を調べます。送受信側のバージョン、時間、フレーム数、エラー、ネットワーク構成を記録してください。ローカルループバックだけでは別の送信元やネットワークを検証できません。

## 配布ツール

```powershell
python -m unittest discover -s tools/tests -v
```

SDK取得、ライセンス収集、ZIP検証ヘルパーを検査します。`licenses/components.json` の必須通知、製品CLIの不在、推移的vcpkg通知も確認します。実際のZIPは[配布](distribution.md)で別途確認してください。パッケージ版のAbout画面では、コンポーネント表、推移的依存、アプリケーションライセンスが表示され、各Licenseリンクから原文を開けることを確認します。

## ドキュメントと例の検証

[profile.example.json](../../examples/profile.example.json) の動画・シナリオの絶対パスを変更し、既存のローダーテスト、またはGUIのApplyで実際のC++ローダーを通してProfileとシナリオ、参照Resizeを確認します。タイマー操作は送りません。

[シナリオ例](../scenarios/examples.md)のYAMLも、参照画像と一緒に保存し、Profileの参照先を変えて確認してください。ConditionやDetectorだけを示した例は、それだけではシナリオとして読み込めません。完全なシナリオの中に埋め込んで試します。

JSONやYAMLの文法として正しいだけでは、アプリの設定として有効とは限りません。また、ローダーテストは動画ファイルをデコードせず、映像とDetectorの寸法も比べません。それらはMonitorで実際の映像を表示するか、フレームを使うテストで確認してください。

ソースへのパスとMarkdownアンカーを確認し、`git diff --check` と `git diff --name-only` で文法・例だけの変更であることも確認します。
