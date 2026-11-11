# Windows 版のメモリ計測

`tools/measure_windows_memory.py` は指定した PID を読み取り、Working Set、Private Bytes、Peak Working Set と区間平均 CPU 使用率を CSV に記録します。OS が対応する場合は Private Working Set も記録します。Python 3.10 以上を使用します。

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

Windows 11 ビルド26200、x64 Release、NDI Runtime 6.3.2.0、320×240・60 fps の NDI 入力から Crop で256×224を取得しました。利用者提供の Profile の3シナリオを YAML 継承対応の Release で読み込み、参照画像をそのまま使いました。Profile のシナリオパスと接続ポートを計測環境に合わせ、10・97・1区間のローカル TestHost へ接続しました。Monitor を表示し、プレビューは閉じた状態で測定しました。[使用した Release の CI](https://github.com/Nanahuse/DivergenceSplitter/actions/runs/43047301442)

シナリオを展開すると、参照画像を使う `detected` は3本で計190件あり、184件は `root_mean_square_similarity` でした。この件数は定義数です。1フレームで評価される条件はタイマー状態と現在の区間に依存します。

## Release のベースライン

| 状態 | フェーズ開始から | Working Set | Private Bytes | Peak Working Set | 区間平均 CPU |
| --- | ---: | ---: | ---: | ---: | ---: |
| 起動のみ | 0秒 | 63.5 MiB | 61.0 MiB | 63.5 MiB | — |
| 起動のみ | 60秒 | 101.0 MiB | 111.6 MiB | 101.1 MiB | 0.30% |
| Profile 読み込み済み、送信元不在 | 0秒 | 393.5 MiB | 413.0 MiB | 393.5 MiB | — |
| Profile 読み込み済み、送信元不在 | 60秒 | 393.9 MiB | 406.3 MiB | 393.9 MiB | 0.47% |
| NDI 受信、判定開始前 | 0秒 | 406.6 MiB | 420.5 MiB | 406.6 MiB | — |
| NDI 受信、判定開始前 | 60秒 | 413.1 MiB | 426.6 MiB | 413.2 MiB | 0.81% |
| 判定中 | 0秒 | 415.0 MiB | 428.2 MiB | 428.4 MiB | — |
| 判定中 | 60秒 | 424.2 MiB | 435.0 MiB | 434.4 MiB | 3.99% |
| 判定中 | 300秒 | 431.2 MiB | 439.3 MiB | 441.9 MiB | 3.33% |
| 判定中 | 1800秒 | 161.7 MiB | 445.0 MiB | 443.1 MiB | 4.00% |

判定中の Private Working Set はスポット測定で399.4 MiB、30分直前に107.8 MiBでした。判定中の3インスタンスは Monitor で約60 fps を示しました。長時間の比較には、常駐ページの変動を受けにくい Private Bytes を使います。

## メモリの内訳

- Profile の読み込みで Private Bytes が294.7 MiB増えました。参照画像をデコードして確認したところ、RMS の元画像38.4 MiB、変換済みの `CV_64F` 画像241.5 MiB、マスク8.3 MiBが長期保持されます。参照パスと ROI の組み合わせは各シナリオ内で合計91通りで、同じ組み合わせの重複分は144.1 MiBです。
- NDI 受信による Private Bytes の増分は20.3 MiBでした。別プロセスの同じ Profile を基準にした差で、SDK の受信バッファ、フレーム変換、プレビュー用フレームなどを含みます。
- 判定を開始して5分後は、受信のみの状態より Private Bytes が12.7 MiB増えました。この差には Bridge の接続、判定、履歴と Monitor の描画用データが含まれます。

別の診断用 Release で、同じ3シナリオを参照画像から作った固定の NDI フレーム列で動かしました。60秒分の履歴が埋まった後の一時点で、257系列に7,592件の履歴サンプルが残っていました。サンプル本体は303,680バイト、サンプルの deque の確保要求は625,552バイト、プレビュー索引用 deque の確保要求は71,760バイトでした。確保要求には deque の管理領域と保持ブロックを含みます。OS のヒープ管理領域や Monitor が作るスナップショットの容量は別に扱います。

診断用 Release の OpenCV `Mat` アロケータでは、Profile 読み込み後に約288.2 MiBが保持されていました。固定フレーム列の実行中に約304.5 MiBまで上がり、その後約288.4 MiBに戻りました。定常区間では60 fps の受信1フレームあたり約14回の `Mat` 確保がありました。アロケータは同時に生存する `Mat` の画像バッファを数えます。NDI SDK や OpenCV が `Mat` 以外で確保した内部メモリは計数の対象外です。

この Profile では RMS が FrameCache に載せるのは判定結果で、RMS の `CV_64F` 変換や差分行列は判定時の一時データです。フレーム画像そのものはインスタンス間で共有されます。最も大きい削減対象はシナリオ読み込み時に作る RMS の参照データでした。

## 固定 NDI フレーム列での回帰確認

変更前後の診断用 Release を、参照画像から作った320×240・60 fps の同じフレーム列で75秒ずつ動かしました。操作を発生させる区間と定常区間を含みます。

| 項目 | 変更前 | 変更後 |
| --- | ---: | ---: |
| Profile 読み込み時の OpenCV `Mat` 保持量 | 288.2 MiB | 144.1 MiB |
| 75秒後の Working Set | 409.1 MiB | 262.3 MiB |
| 75秒後の Private Bytes | 415.3 MiB | 268.8 MiB |
| 60〜75秒のプロセス平均 CPU 使用率 | 1.55% | 1.69% |
| 受信 FPS（終盤の表示値） | 60.05 | 59.98 |
| 平均判定時間（インスタンス順） | 1.738 / 1.759 / 0.318 ms | 1.735 / 1.762 / 0.318 ms |
| プレビューを開いたときの Private Bytes 増分 | 0.3 MiB | 0.4 MiB |
| Profile 再読み込み後の Peak Working Set | 695.9 MiB | 410.3 MiB |

Start、Split、Reset の計11操作はインスタンスごとの順序と結果が一致しました。Profile 再読み込み後は3接続とも Ready に戻り、送信元の停止・再起動後は約60 fps の受信に復帰しました。再読み込み時のピークは、切り替え前の状態を保持したまま次のシナリオを構築する区間を含みます。
