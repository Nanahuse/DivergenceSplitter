# 現行Windows配布物の実測（2026-10-22）

比較元は [Windows distribution run 38922970221](https://github.com/Nanahuse/DivergenceSplitter/actions/runs/38922970221) の `DivergenceSplitter-windows-x64`。main commitは `f3ecd17f9ba8d1653808072f7447c494c00ad526`、Artifact IDは `12055417786`。取得時点の保存期限は2027-01-14。

| 測定項目 | bytes | MiB |
| --- | ---: | ---: |
| GitHub Actionsから取得した元ZIP | 119,173,986 | 113.65 |
| 展開後合計（3,727ファイル） | 336,741,879 | 321.14 |
| 比較条件で作り直したZIP | 120,071,454 | 114.51 |

元ZIPのSHA256は `c17638a2e7dd7572cc7a2bddffa5f12da92a9c816e5a52726f18bb250e82b494`。GitHub APIのArtifact digestと、ダウンロードしたZIPのハッシュの一致を確認した。

Artifact内のdist-infoで、Flet `1.0.4`、opencv-contrib-python `5.0.0.93`、NumPy `2.5.4`、ndi-python `6.3.2.5` を確認した。C++実験のOpenCV `4.12.0#7` とはバージョンと標準機能の構成が異なるため、容量差を言語の違いだけによる効果とは解釈しない。

再圧縮は `tools/measure_distribution.py`、Python 3.14.6、zlib `1.3.1.zlib-ng`、DEFLATE level 6、全ファイルの固定時刻2020-01-01、パス順、共通の `distribution/` 接頭辞を使用した。元ZIPと再圧縮ZIPはヘッダー・圧縮実装・パスなどの条件が異なるので、サイズの差を容量削減として解釈しない。

区分はパスに基づく分類であり、厳密な所有関係は推定。以下のbytesは各区分に割り当てたファイルの実測合計で、全体を重複なく分割している。

| 区分 | bytes | MiB |
| --- | ---: | ---: |
| 本体exe | 184,220 | 0.18 |
| Flet/Flutter（Dartのapp.so、ICUデータを含む） | 46,016,144 | 43.88 |
| Python（標準DLL、その他パッケージを含む） | 57,703,920 | 55.03 |
| OpenCV + NumPy | 199,826,100 | 190.57 |
| NDI（Python bindingと付属文書を含む） | 30,666,116 | 29.25 |
| MSVC Runtime | 872,240 | 0.83 |
| その他 | 1,473,139 | 1.40 |

主要なファイルは次のとおり。

| パス（DivergenceSplitter/ 以下） | bytes |
| --- | ---: |
| site-packages/cv2/cv2.pyd | 112,898,048 |
| site-packages/cv2/opencv_videoio_ffmpeg500_64.dll | 30,876,160 |
| site-packages/NDIlib/Processing.NDI.Lib.x64.dll | 29,863,120 |
| flutter_windows.dll | 21,284,864 |
| site-packages/numpy.libs/libscipy_openblas64_-ed4f167a5330424524f45258e7ca2c8d.dll | 20,589,056 |
| data/app.so | 16,319,376 |
| python314.dll | 7,046,656 |

既存Artifactには `_d.pyd` や `_d.dll` も存在する。比較元の内容はそのまま集計・再圧縮しており、今回の基準値からファイルを取り除いてはいない。NDIのDLL自体は29,863,120 bytesだが、C++版で使う公式SDKと同じバージョンになるとは限らないため、この数値をC++版へ転記しない。

機械可読な要約と上位20ファイルは [legacy-summary.json](legacy-summary.json)。ローカルの全ファイルCSV/JSONと再圧縮ZIPは `build/size-probe/legacy-report/` に保存した。CIでは同じ形式の全一覧をArtifactに保存する。

C++版との容量比較は、C++ビルド・配布起動テスト・同条件のZIP生成後にのみ行う。完全な移植版の容量はまだ推定していない。
