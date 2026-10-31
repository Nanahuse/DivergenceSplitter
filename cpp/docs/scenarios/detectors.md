# Detectorリファレンス

[日本語（正本）](detectors.md) | [English](detectors.en.md)

[シナリオ作成](README.md) · [detected](conditions.md#detected) · [例](examples.md)

Detectorは数値のスコアを返し、[`detected`](conditions.md#detected) が `>=` で `minimum_score` と比較します。9種類すべての出力を `[0, 1]` に制限します。方式に応じ、一致度、明るさ、指定色の割合が高いほどスコアが大きくなります。確率ではなく、方式間でしきい値を共用できるわけでもありません。成立させたい画面と、それ以外の画面をDiagnosticsで比較して調整してください。

## 共通設定とROI

全Detectorに `type` が必要で、任意の `roi` を指定できます。参照画像を使う型は `reference` も必須です。`hash_size` は `difference_hash_similarity`、`lower`／`upper` は `color_range` だけの項目です。他の設定項目はありません。

```yaml
type: template_match
reference: images/title.png
roi: {x: 100, y: 50, width: 320, height: 180}
```

`roi` の省略または `null` は正規化した画像全体を使います。指定時は4項目すべてが整数で必要です。`x`／`y` は0以上、`width`／`height` は正の値です。原点は入力のCrop／Resize後の画像の左上です。矩形は実フレーム内に収まる必要があり、自動では切り詰めません。

ROIは入力から調べる領域を選びます。参照画像を切り取る指定ではありません。以下の寸法制約は参照画像とこの入力領域の間で比較します。

## 参照画像とチャンネル

参照パスは[YAMLの保存場所](yaml-reference.md#パス)を基準にします。チャンネルとビット深度を強制変換せず読み込みます。通常は8ビットBGR／BGRAのPNGを使えます。グレースケールPNGは1チャンネルのままで、色・画素比較向けに自動でBGRへ変換しません。

共通の前処理は1チャンネルのグレースケール、3チャンネルのBGR、4チャンネルのBGRAを受理します。BGRAはBGRとalphaに分け、alphaが0または255だけで、少なくとも1ピクセルが不透明であることを検査します。中間alphaと全透過画像は拒否します。全ピクセルが不透明ならalphaを除き、マスクなしとして扱います。マスクの使い方は方式ごとに異なります。

| Detector | 入力と参照画像の寸法・チャンネル | 透過ピクセルの扱い |
| --- | --- | --- |
| `template_match` | 参照の幅・高さは領域以下。alpha除去後のチャンネル数が一致すること。 | 二値マスクで相関を計算。 |
| `mean_absolute_similarity`、`root_mean_square_similarity` | 幅・高さと、alpha除去後のチャンネル数が完全一致。 | 誤差と成分数から除外。 |
| `histogram_similarity`、`perceptual_hash_similarity` | 入力は8ビットBGR、参照は8ビットBGR／BGRA。マスクなしなら寸法が異なってもよく、ありなら領域と完全一致。 | histogramは除外し、perceptual hashは両画像の同じ位置を黒にする。 |
| `difference_hash_similarity` | 寸法の違いとグレースケール／BGR／BGRAを許容し、グレースケールへ変換。 | alphaを検証して除くが、マスクは使わない。 |
| `phase_correlation` | 幅・高さが完全一致。グレースケール／BGR／BGRAを浮動小数点グレースケールへ変換。 | alphaを検証して除くが、マスクは使わない。 |

templateと画素誤差の方式は、通常のBGR入力に合わせてグレースケール参照を自動変換しません。BGR入力にはBGR参照を使ってください。画素誤差は浮動小数点で計算しますが、正規化の基準は255なので8ビット参照が適切です。templateは画像を互換な8ビットまたは浮動小数点に変換しますが、16ビットの輝度範囲を0～255へ正規化しません。

histogramとperceptual hashは8ビット以外の参照を明示的に拒否します。グレースケールを使うhashとphaseは内部で浮動小数点へ変換します。空画像や不適合な構造は読み込み・評価のエラーになり、検出成功としては扱いません。

Profileの [`resize_references`](../configuration.md#cropresize参照画像) は読み込み時に参照寸法を変える場合があります。Applyでは参照を構築しますが、領域の範囲や実フレームの形状・チャンネルとの互換性にはフレームが必要です。

## 方式の選び方

| 用途 | 最初に試す方式 |
| --- | --- |
| 領域内の異なる位置から特徴的な小画像を探す | `template_match` |
| 固定した画面・ROIを画素単位で比べる | `mean_absolute_similarity` |
| 大きな画素誤差を強く減点する | `root_mean_square_similarity` |
| 配置より色の分布を比べる | `histogram_similarity` |
| 寸法が違う画像のおおまかな構造を比べる | `perceptual_hash_similarity`、`difference_hash_similarity` |
| 参照なしで明暗の変化を調べる | `mean_brightness` |
| 領域内の指定色の割合を調べる | `color_range` |
| 同寸法の画像を平行移動に対応した相関で比べる | `phase_correlation` |

この表は選択の目安であり、精度の保証ではありません。hashやhistogramは無関係な画面にも高スコアを返す場合があります。意味のあるROI、追加のCondition、代表的なテスト画像を組み合わせてください。

## template_match

```yaml
type: template_match
reference: images/title.png
```

`reference` は必須、`roi` は任意です。テンプレートが収まる領域内の全位置で正規化相関を調べ、最大値を使います。

- マスクなし：OpenCVの `TM_CCOEFF_NORMED` でチャンネルごとの平均を差し引きます。最大相関 `r` の範囲は `[-1, 1]` で、スコアは `clamp((r + 1) / 2)` です。相関0のスコアは約 `0.5` であり、0ではありません。
- マスクあり：不透明ピクセルで `TM_CCORR_NORMED` を計算します。同じ平均除去は行わず、最大相関を直接 `[0, 1]` に制限します。

少なくとも1チャンネルに位置による値の変化が必要で、一様な参照は拒否します。領域より大きい参照やチャンネル数の不一致は評価エラーです。相関が非有限値でもエラーです。スケールが安定した記号・文字に向きますが、任意の拡大縮小・回転は探索せず、一致位置をConditionへ返す機能もありません。

## mean_absolute_similarity

```yaml
type: mean_absolute_similarity
reference: images/screen.png
```

`reference` は必須、`roi` は任意です。選択した画素成分数を `N`（不透明ピクセル数×チャンネル数）、入力と参照の成分差を `d_i` とすると、スコアは `clamp(1 - (sum(abs(d_i)) / N) / 255)` です。

同一画像は1になり、平均画素誤差が大きいほど下がります。寸法とチャンネル数の完全一致が必要です。固定位置のUIや画面に向きますが、移動、圧縮ノイズ、明るさの変化に影響されます。

## root_mean_square_similarity

```yaml
type: root_mean_square_similarity
reference: images/screen.png
```

`reference` は必須、`roi` は任意です。成分の選択は前項と同じで、スコアは `clamp(1 - sqrt(sum(d_i * d_i) / N) / 255)` です。

寸法とチャンネル数の完全一致が必要です。二乗するため、一部の大きな誤差をmean absolute方式より強く反映します。局所的な不一致でスコアを大きく下げたい場合に使います。

## histogram_similarity

```yaml
type: histogram_similarity
reference: images/screen.png
```

`reference` は必須、`roi` は任意です。各色8ビン、合計512ビンのRGB結合ヒストグラムを、各色の値の範囲 `[0, 256)` で作成してL2正規化します。OpenCVのBhattacharyya距離を `D` とし、スコアは `clamp(1 - D)` です。距離計算はヒストグラム総量で係数を正規化した後に平方根を使います。色分布が一致すると1です。

入力は8ビットBGRが必要です。8ビットBGRA参照は二値マスクを供給します。マスクなしなら寸法が異なってもよく、ありなら同じ位置を選べるよう領域と寸法を一致させます。空間配置は使わないため、画素を並べ替えても分布が同じなら1になる場合があります。画面全体の色変化には使えますが、似た配色のレイアウトを単独で区別する用途には向きません。

## perceptual_hash_similarity

```yaml
type: perceptual_hash_similarity
reference: images/screen.png
```

`reference` は必須、`roi` は任意です。マスクがあれば各画像の該当位置を黒にし、area補間で8×8に縮小した後、exact linear補間で32×32へ拡大します。8ビットグレースケール、次に浮動小数点へ変換してDCTを行います。左上8×8の係数を取り、DC成分を0にし、そのブロックの平均より大きいかで64ビットを作ります。

スコアは `clamp(1 - HammingDistance / 64)` です。元画像が異なってもhashが同じなら1です。入力・参照は8ビットBGRが必要で、参照には検証済みalphaを付けられます。マスクなしなら寸法差を許容し、ありなら寸法一致が必要です。寸法が変わるおおまかな構造の比較に使えますが、小さなhashでは細部の違いを見落とす場合があります。

## difference_hash_similarity

```yaml
type: difference_hash_similarity
reference: images/screen.png
hash_size: 8
```

`reference` は必須、`roi` と `hash_size` は任意です。`hash_size` は正の整数で、既定値は8です。浮動小数点グレースケールへ変換し、area補間で `(hash_size + 1) × hash_size` にResizeします。横に隣り合う値で右が左より大きい場合にビットを立て、`hash_size²` ビットを作ります。スコアは `clamp(1 - differing_bits / hash_size²)` です。

元画像の寸法差とグレースケール・カラーの違いを許容します。参照alphaは検証しますが、マスクは使いません。色や正確な画素値ではなく、横方向の強度変化を比べます。`hash_size` を増やすと細部と計算量が増えますが、hashの衝突をなくすものではありません。

## mean_brightness

```yaml
type: mean_brightness
roi: {x: 0, y: 0, width: 100, height: 100}
```

`type` 以外に必須項目はなく、`roi` は任意です。参照画像は不要です。スコアは `clamp(mean_of_all_pixel_components / 255)` です。チャンネル平均を等しく平均し、知覚重み付きのグレースケール輝度は使いません。通常の8ビット入力では黒が0、白が1です。

グレースケールとBGRを使えます。BGRAを与えるとalphaも平均に含みますが、通常のNDI入力は検出前にalphaを除去します。フェードなどの明暗判定に使え、特定の画面を識別する方式ではありません。しきい値未満の暗さを判定するには `detected` を `not` で包みます。

## color_range

```yaml
type: color_range
lower: [0, 0, 180]
upper: [80, 80, 255]
```

`lower` と `upper` は必須、`roi` は任意です。上下限は同じ長さのリストで、グレースケールなら1成分、カラーなら3成分です。3成分の順序はB、G、Rであり、RGBやHSVではありません。各値は有限数とし、下限を上限以下に指定してください。リストの長さは入力チャンネル数と一致させます。通常の入力は0～255ですが、ローダーは値をこの範囲に制限しません。

全チャンネルが上下限の範囲内にある画素を一致とし、境界値も含みます。スコアは領域の `matching_pixels / total_pixels` です。例は主に赤いピクセルの割合を調べます。色空間変換と参照画像は使いません。単色の表示やオーバーレイに使えます。

## phase_correlation

```yaml
type: phase_correlation
reference: images/screen.png
```

`reference` は必須、`roi` は任意です。同寸法の画像を浮動小数点グレースケールに変換し、窓を指定せずOpenCVの `phaseCorrelate` を使います。スコアは返されたresponse（正規化した相関ピークの応答）を `[0, 1]` に制限した値です。平行移動量は破棄するため、スコアは移動量や直接の画素誤差による類似度ではありません。

グレースケールに変換できれば入力と参照のチャンネル数は異なっても構いません。alphaを検証しますがマスクは使いません。寸法は完全一致が必要です。明確な相関ピークを持つ模様を使ってください。一様・曖昧なパターンは参照に向きません。responseが非有限値の場合は評価エラーです。
