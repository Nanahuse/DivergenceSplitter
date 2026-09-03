# パフォーマンスレポート

リポジトリに含まれる計測スクリプトは、次のコマンドで実行する。

```console
uv run python benchmarks/measure_processing.py --duration 5
```

このワークロードは、事前に確保したBGRフレームを60 fps周期で実際の単一スロット
`LatestFrameBuffer`へ供給する。処理スレッドはフレームごとに
`MeanBrightnessDetector`、`ColorRangeDetector`、
`DifferenceHashSimilarityDetector`、`TemplateMatchDetector`を1回ずつ評価し、
その後にキャッシュ済み結果を1回取得する。取得から処理完了までのp95遅延、Detector
処理のp95遅延、キャッシュヒットのp95遅延、上書きされたフレーム数、およびPythonが
追跡したピークメモリを出力する。カメラドライバによるコピー、Scenario固有の参照画像、
ネットワーク遅延は再現しない。

## 2026-09-03 基準値

Windows開発環境で測定した環境情報と結果を、以下の1行ログとして記録する。これらの値を
処理能力の保証として扱う前に、リリース対象のハードウェアで同じコマンドを再実行する。

```text
benchmark.environment python=3.14.6 platform=Windows-11-10.0.26200-SP0 duration_seconds=5.0 target_input_fps=60.0 scenario=four_builtin_detectors bridge=not_measured
benchmark.processing resolution=640x360 input_fps=59.84 processing_fps=55.05 published=300 processed=276 overwritten=24 capture_to_completed_p95_ms=33.208 detectors_p95_ms=18.995 cache_hit_p95_ms=0.008 peak_traced_mib=4.309 detector.MeanBrightnessDetector.p95_ms=0.506 detector.ColorRangeDetector.p95_ms=0.512 detector.DifferenceHashSimilarityDetector.p95_ms=4.299 detector.TemplateMatchDetector.p95_ms=14.628
benchmark.processing resolution=1280x720 input_fps=59.22 processing_fps=15.00 published=300 processed=76 overwritten=224 capture_to_completed_p95_ms=82.298 detectors_p95_ms=69.044 cache_hit_p95_ms=0.006 peak_traced_mib=17.185 detector.MeanBrightnessDetector.p95_ms=1.570 detector.ColorRangeDetector.p95_ms=2.066 detector.DifferenceHashSimilarityDetector.p95_ms=10.537 detector.TemplateMatchDetector.p95_ms=55.997
```

720pのワークロードでは、すべての入力フレームを処理できていない。バッファは有限のまま
古いフレームを破棄するが、Detector全体の処理時間が現在のボトルネックである。並列化を
検討する前に、再測定時のDetector別フィールドから支配的なDetectorを特定する。

15秒の確認計測では、640x360で900フレーム中831フレームを処理し、追跡対象のピーク
メモリは4.453 MiBだった。1280x720では900フレーム中224フレームを処理し、ピークは
17.224 MiBだった。5秒計測時のピーク（4.309 MiB、17.185 MiB）と比較すると、入力が
600フレーム増えても差はどちらも0.15 MiB以内だった。`TemplateMatchDetector`は
引き続き支配的なDetectorで、p95はそれぞれ14.501 msと57.813 msだった。

## 初期SLO

記録した4種類のDetectorを使うワークロードに対して、次を初期SLOとする。

- 実測入力スループットを58 fps以上に保つ。
- 処理スループットを640x360では50 fps以上、1280x720では14 fps以上に保つ。
- 取得から処理完了までのp95遅延を640x360では50 ms未満、1280x720では100 ms未満に
  保つ。
- 単一スロットバッファへフレームを蓄積せず、計測時間を延ばしても追跡対象のピークメモリを
  安定させる。
- キャッシュ済みDetector結果の取得にかかるp95遅延を0.10 ms未満に保つ。

60 fpsの全フレームを処理することは性能目標であり、初期SLOには含めない。現在は両解像度
とも未達である（55.05 fps、15.00 fps）。Runtimeは性能不足時にキューを増大させず、古い
フレームを観測可能な形で上書きする。並列化を検討する前に、計測で特定したDetectorの
ボトルネックを最適化する。

Bridge遅延にはローカル環境のSLOを設定しない。プロセス内のテストダブルでは、ZeroMQ、
LiveSplitのUIスレッド、ホスト負荷を再現できないためである。RuntimeログからBridgeの
タイムアウトとAction結果を識別できる。リリース前に、配備先ホストでエンドツーエンドのBridge遅延
基準を記録する。
