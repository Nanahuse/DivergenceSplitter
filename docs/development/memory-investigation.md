# Windows 版のメモリ計測

`tools/measure_windows_memory.py` は指定した PID を読み取り、Working Set、Private Bytes、Peak Working Set と区間平均 CPU 使用率を CSV に記録します。Python 3.10 以上を使用します。

- Working Set はその時点で物理メモリ上にあるプロセスのページです。共有ページも含みます。
- Private Bytes はプロセス固有のコミット量です。
- Peak Working Set はプロセス起動からの最大値です。フェーズを切り替えてもリセットされません。
- CPU 使用率は連続する2サンプル間のプロセス CPU 時間を論理プロセッサ数で割った値です。最初の行には区間平均がありません。

タスクマネージャーで比較するときは列名も記録してください。「メモリ」列のプライベート ワーキング セットは、Working Set や Private Bytes と値が異なります。[Windows のメモリカウンター](https://learn.microsoft.com/en-us/windows/win32/memory/memory-performance-information)

## 測定手順

1. 実行ファイルのビルド種別、コミット、Windows のバージョン、NDI Runtime、送信元の解像度と FPS、Crop または Resize、シナリオ、インスタンス数を記録します。比較では同じ Release 構成を使います。
2. 作業用の `APPDATA` を指定して新しいプロセスを起動します。Profile なしの起動時、送信元が不在の Profile、NDI 受信のみ、実際に判定する状態を順に測ります。送信元を制御できない場合は、送信元不在の Profile を別プロセスで測ります。
3. 判定を始める前に、各インスタンスを接続先が用意された隔離タイマーへ向けます。各タイマーには対応するシナリオの区間数を用意し、Monitor で受信と判定が継続していることを確認します。
4. 各フェーズの開始時に計測を起動します。既定では開始直後、60秒後、300秒後、1800秒後に記録します。短い切り分けには `--at 0 60` を使えます。CSV の時刻は UTC、容量はバイト単位です。

```powershell
python tools/measure_windows_memory.py --pid 12345 --build Release --revision <commit> --phase evaluation --output build/evaluation.csv
```

同じ入力で比較する際は Monitor とプレビューの表示状態、画面 DPI、タイマーの状態も揃えます。再接続や Profile 再読み込みはイベントの時刻を記録し、定常状態のサンプルと区別します。

## 調査条件

Windows 11 ビルド26200、x64 Release、NDI Runtime 6.3.2.0、320×240 の NDI 入力から Crop で256×224を取得しました。添付 Profile の3シナリオを YAML 継承対応の Release で読み込み、参照画像をそのまま使いました。Profile のシナリオパスと接続ポートを計測環境に合わせ、各シナリオに対応する区間数のローカル TestHost へ接続しました。[使用した Release の CI](https://github.com/Nanahuse/DivergenceSplitter/actions/runs/43047301442)

添付シナリオを展開すると、参照画像を使う `detected` は3本で計190件あり、184件は `root_mean_square_similarity` でした。この件数は定義数です。1フレームで評価される条件はタイマー状態と現在の区間に依存します。
