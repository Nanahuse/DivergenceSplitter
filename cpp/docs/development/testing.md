# テスト

[日本語（正本）](testing.md) | [English](testing.en.md)

[開発ガイド](README.md) · [ビルド環境](building.md)

## CTest

対応するプリセットを設定した後、`cpp/` で実行します。

```powershell
cmake --build --preset full --parallel
ctest --preset full --output-on-failure
ctest --preset full -N
ctest --preset full -R 'Conditions|ScenarioLoader|ScenarioRuntime' --output-on-failure
```

検証する構成に合わせて `core`、`core-release`、`full-release` も使えます。coreではQtのテストを含まず、NDIの既定値はOFFです。CMakeはGoogleTestの個別ケースとQtの実行ファイルを登録します。Qtはoffscreenと設定済みプラグイン・DLLパスを使い、CTestが環境を設定します。

| 分野 | 主なテストと確認対象 |
| --- | --- |
| Detector | [detector_tests.cpp](../../tests/detector_tests.cpp)：計算式、alphaマスク、寸法・チャンネル制約、hash、histogram、相関。 |
| Condition | [condition_tests.cpp](../../tests/condition_tests.cpp)：短絡順序、edge履歴、elapsedの開始、Holdの連続成立、Once／Nth、Thenの進行・リセット。 |
| YAML | [scenario_loader_tests.cpp](../../tests/scenario_loader_tests.cpp)：スキーマエラー、入れ子の条件、パス、ROI、参照変換。 |
| Profile | [profile_tests.cpp](../../tests/profile_tests.cpp)：JSON項目、入力型、設定、保存形式。 |
| Capture | [camera_tests.cpp](../../tests/camera_tests.cpp)、[normalizer_tests.cpp](../../tests/normalizer_tests.cpp)、[ndi_tests.cpp](../../tests/ndi_tests.cpp)：機器の特定、画像変換、fake NDIの寿命・形式・タイムアウト・復帰。 |
| キャッシュ・Runtime | [frame_cache_tests.cpp](../../tests/frame_cache_tests.cpp)、[scenario_runtime_tests.cpp](../../tests/scenario_runtime_tests.cpp)、[instance_runtime_tests.cpp](../../tests/instance_runtime_tests.cpp)：共有評価、Phase選択、リセット、fake Bridge送信、反応時間中の自動・手動Reset、通常ActionとResetの別々の確定待ち、遅延イベント、入力停止中の期限切れ、Reset拒否後のQuery、再接続・結果不明時の処理。 |
| UI・ログ | [ui_tests.cpp](../../tests/ui_tests.cpp)、[logging_tests.cpp](../../tests/logging_tests.cpp)：下書きプレビューの入力排他・非表示時の解放・一時停止入力の変換・エラー復旧、参照検証、検索・プレビュー中の応答性、MonitorのCondition概要、Reset Allの長押し・中断、Widget、ログのローテーション。 |

fakeのテストはアプリの動作を決定的な条件で検査します。物理カメラ、外部送信元、利用者のLiveSplit環境の動作確認とは別です。

## 録画を使うE2Eテスト

[recorded_pipeline_tests.cpp](../../tests/recorded_pipeline_tests.cpp)はMJPEG AVI、JSON Profile、YAMLを生成し、実際のデコード、Crop／Resize、CapturePipeline、Scenario評価、InstanceRuntimeを通してfake Bridgeの操作履歴を確認します。Start／Split、外部Undo後の再判定、共有フレーム上の複数シナリオの独立性を検証します。フレームごとの完了待ちで入力順と操作履歴を比較するため、実際の無制限な取得速度を再現する試験ではありません。

VideoFileSourceのテストは内蔵MJPEGデコーダーの優先使用とWindowsのH.264フォールバックを確認し、RecordedPipelineには低FPS動画の停止応答も含みます。CTestの `recorded_pipeline_repeat` は録画・デコーダーのケースを新しいプロセスで20回実行し、起動時の不安定さも検査します。

```powershell
ctest --preset full -R 'RecordedPipeline|VideoFileSource|recorded_pipeline_repeat' --output-on-failure
```

実Bridgeへの送信まで含む録画テストは次のTestHost構成で実行します。

## 実LiveSplit.Bridge TestHostとの結合

任意の実行ファイルを有効にします。

```powershell
cmake --preset full -DDIVERGENCESPLITTER_BUILD_TESTHOST_TESTS=ON
cmake --build --preset full --parallel
```

[cpp23.yml](../../../.github/workflows/cpp23.yml) と同じ固定リビジョンのBridge TestHostを別のディレクトリでビルドします。Gitと.NET SDK 10を使ってください。Bridgeリポジトリ側のビルド要件も満たす必要があります。

```powershell
git clone --recurse-submodules https://github.com/Nanahuse/LiveSplit.Bridge.git C:/src/LiveSplit.Bridge-TestHost
git -C C:/src/LiveSplit.Bridge-TestHost checkout 4c14c0161eacd50b05411c0d20f5eff523e9c155
git -C C:/src/LiveSplit.Bridge-TestHost submodule update --init --recursive
dotnet build C:/src/LiveSplit.Bridge-TestHost/tests/LiveSplit.Bridge.TestHost/LiveSplit.Bridge.TestHost.csproj --configuration Release
```

`cpp/` に戻り、未使用のローカルポートで既存ランナーを実行します。

```powershell
python tools/run_testhost.py --testhost C:/src/LiveSplit.Bridge-TestHost/tests/LiveSplit.Bridge.TestHost/bin --test-exe build/full/divergencesplitter_testhost_tests.exe --port 54157
```

ヘルパーはTestHostを起動し、標準入力を開いたままREADYを待ちます。`DIVERGENCESPLITTER_TESTHOST_PORT` と `DIVERGENCESPLITTER_TESTHOST_ALLOW_CONTROL=1` を設定してテストを行い、最後にTestHostを止めます。テストはQuery・Event、Pause／Resumeと、`TestHost.RecordedVideoThroughYamlToRealBridgeControls` による録画→YAML→実BridgeへのStart／Split送信を確認します。録画テストは操作数、最後のSplitの成功、実タイマーのSplit位置1、動画の終端を検証します。

制御テストはTestHostの既定の2区間Runを必要とし、タイマーの開始・Split・Resetも行います。隔離したTestHostを使い、本番LiveSplitのポートには接続しないでください。

自分で起動したHostには、CTest前に `DIVERGENCESPLITTER_TESTHOST_PORT` を設定します。未設定ならテストをスキップするため、CTest成功だけでは実Bridgeの制御確認になりません。制御には `DIVERGENCESPLITTER_TESTHOST_ALLOW_CONTROL=1` も必要です。`--testhost` にディレクトリを指定する場合、その中のTestHost実行ファイルは1つである必要があります。

## 実NDIの検証

固定SDKでNDIを有効にした構成で実行します。

```powershell
ctest --preset full-release -R '^ndi_sdk_' --output-on-failure
$env:NDI_SOAK_SECONDS = '600'
.\build\full-release\divergencesplitter_ndi_loopback_tests.exe
Remove-Item Env:NDI_SOAK_SECONDS
```

`ndi_sdk_initialization` は初期化・終了を確認します。`ndi_sdk_loopback` は実SDKのローカル送信元を作り、検索、選択、受信BGR変換、Crop／Resize、プレビュー、シナリオのStart判定、送信元の破棄・再作成、再接続、終了を検証します。継続時間は最大3600秒にできます。CTestのタイムアウトは90秒なので、長時間の実行では例のように実行ファイルを直接呼んでください。

[NDI Tools](https://ndi.video/tools/) などの独立した送信元でも対象ネットワークを確認してください。選択、プレビュー、判定、停止・再開後の復帰、保存Profileの再読込、継続受信を調べます。送受信側のバージョン、時間、フレーム数、エラー、ネットワーク構成を記録してください。ローカルループバックだけでは別の送信元・ネットワークを検証できません。

## 配布ヘルパー

```powershell
python -m unittest discover -s tools/tests -v
```

SDK取得とZIP検証ヘルパーを検査します。実際のZIPは[配布手順](distribution.md)で別途確認してください。

## ドキュメントの例の検証

[profile.example.json](../../examples/profile.example.json) の動画・シナリオの絶対パスを変更し、ビルドしたCLIの `--profile <path> --check` を実行します。実際のC++ローダーでProfileとシナリオ、参照Resizeを確認し、タイマー操作は送りません。

[シナリオ例](../scenarios/examples.md)の完全なYAMLも参照画像と一緒に保存し、Profileの参照先を変えて確認します。ConditionやDetectorだけの断片は完全なシナリオに埋め込んでください。JSON／YAMLの構文解析だけではスキーマ検証になりません。`--check` は動画・コーデックを開かず、実フレームとDetectorの寸法比較もしないため、Monitorかフレームを使うテストで確認してください。

ソースへのパスとMarkdownアンカーを確認し、`git diff --check` と `git diff --name-only` で文書・例だけの変更であることも確認します。
