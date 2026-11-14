# Detectorリファレンス

[シナリオ作成](README.md) · [detected](conditions.md#detected) · [例](examples.md)

## 目次

### 共通仕様

- [方式の選び方](#方式の選び方)
- [共通設定とROI](#共通設定とroi)
- [参照画像とチャンネル](#参照画像とチャンネル)
- [スコアの計算](#スコアの計算)

### Detector一覧

- [template_match](#template_match) — 映像の中から参照画像と似た部分を探す
- [mean_absolute_similarity](#mean_absolute_similarity) — 位置が固定された画面を、同じ位置の画素の差で比べる
- [root_mean_square_similarity](#root_mean_square_similarity) — 固定位置の画面を比べ、大きな画素の違いを強く反映する
- [histogram_similarity](#histogram_similarity) — 画素の配置に関係なく、画面の色の分布を比べる
- [perceptual_hash_similarity](#perceptual_hash_similarity) — 寸法が違う画面のおおまかな構造を比べる
- [difference_hash_similarity](#difference_hash_similarity) — 横方向の明暗の変化から、画面のおおまかな模様を比べる
- [mean_brightness](#mean_brightness) — 参照画像を使わず、映像の平均的な明るさを調べる
- [color_range](#color_range) — 指定した色の範囲に入る画素の割合を調べる
- [phase_correlation](#phase_correlation) — 同じ模様が平行移動した画面の相関を調べる

## 方式の選び方

Detectorは、画像の一致度や明るさなどを0〜1のスコアで返します。[detected](conditions.md#detected)は、そのスコアが `minimum_score` 以上になると成立します。

1. 映像のどこを調べるか決めます。画面の一部だけで判定できる場合は、[ROI](#共通設定とroi)を指定します。
2. [Detector一覧](#detector一覧)から用途に合う方式を選びます。参照画像を使う場合は[寸法とチャンネルの条件](#参照画像とチャンネル)を確認します。
3. [MonitorのCompare detectors](../user-guide.md#detectorの比較)で、検出したい場面と誤検出しやすい場面のスコアを比べ、しきい値を調整します。方式を変えた場合は、同じしきい値で判定できるか改めて確認してください。

## 共通設定とROI

`type` は必須です。方式ごとに表にある項目を指定できます。`roi` はどのDetectorでも省略できます。

```yaml
type: template_match
reference: images/title.png
roi: {x: 100, y: 50, width: 320, height: 180}
```

`roi` を省略するか `null` にすると、Crop／Resize後の画像全体を調べます。一部だけを調べる場合は、`x`、`y`、`width`、`height` の4項目をすべて整数で指定してください。

`x` と `y` は左上の位置で、0以上です。`width` と `height` は範囲の幅・高さで、0より大きい値を指定します。座標の基準はCrop／Resize後の画像の左上です。指定した範囲が映像からはみ出すとエラーになり、自動では切り詰めません。

ROIは入力映像の範囲だけを指定します。参照画像との寸法の条件は、[参照画像とチャンネル](#参照画像とチャンネル)を参照してください。

## template_match

位置が変わる記号や文字など、同じ大きさで映る目印を探す場合に使います。

```yaml
type: template_match
reference: images/title.png
```

| 設定項目 | 必須・任意 | 指定する値 |
| --- | --- | --- |
| `reference` | 必須 | [参照画像](#参照画像とチャンネル)のパス。 |
| `roi` | 任意 | [調べる範囲](#共通設定とroi)。省略時は画像全体。 |

調べる範囲の中で参照画像を重ねる位置を変えて比較し、最も高い相関をスコアに使います。

参照画像は調べる範囲に収まる寸法にし、色や明るさに変化があるものを使います。探す対象の拡大・縮小や回転には対応していません。Conditionで使えるのはスコアです。

## mean_absolute_similarity

位置が固定されたUIや画面を参照画像と比べる場合に使います。

```yaml
type: mean_absolute_similarity
reference: images/screen.png
```

| 設定項目 | 必須・任意 | 指定する値 |
| --- | --- | --- |
| `reference` | 必須 | [参照画像](#参照画像とチャンネル)のパス。 |
| `roi` | 任意 | [調べる範囲](#共通設定とroi)。省略時は画像全体。 |

同じ位置の画素を比較し、成分ごとの絶対差の平均が小さいほどスコアが高くなります。同じ画像なら1です。

調べる範囲と参照画像の寸法・チャンネル数を合わせます。位置ずれ、圧縮ノイズ、明るさの変化でもスコアが下がります。

## root_mean_square_similarity

画面の一部に大きな違いがあるとき、`mean_absolute_similarity` よりスコアを大きく下げたい場合に使います。

```yaml
type: root_mean_square_similarity
reference: images/screen.png
```

| 設定項目 | 必須・任意 | 指定する値 |
| --- | --- | --- |
| `reference` | 必須 | [参照画像](#参照画像とチャンネル)のパス。 |
| `roi` | 任意 | [調べる範囲](#共通設定とroi)。省略時は画像全体。 |

同じ位置の画素を比較し、成分ごとの差の二乗平均平方根が小さいほどスコアが高くなります。

調べる範囲と参照画像の寸法・チャンネル数を合わせます。カラー画像はBGRの成分を比較し、入力側のalphaは無視します。参照画像の透明部分は比較から除外します。

## histogram_similarity

画面全体の配色の変化を判定する場合に使います。

```yaml
type: histogram_similarity
reference: images/screen.png
```

| 設定項目 | 必須・任意 | 指定する値 |
| --- | --- | --- |
| `reference` | 必須 | [参照画像](#参照画像とチャンネル)のパス。 |
| `roi` | 任意 | [調べる範囲](#共通設定とroi)。省略時は画像全体。 |

色の分布が近いほどスコアが高くなります。分布が同じなら、配置が違っていてもスコアは1です。

入力と参照画像は8ビットカラーを使います。透過部分を除外する場合は、参照画像と調べる範囲の寸法を合わせます。

## perceptual_hash_similarity

画像の大きさが異なっていても、全体の構造が似ているかを調べたい場合に使います。

```yaml
type: perceptual_hash_similarity
reference: images/screen.png
```

| 設定項目 | 必須・任意 | 指定する値 |
| --- | --- | --- |
| `reference` | 必須 | [参照画像](#参照画像とチャンネル)のパス。 |
| `roi` | 任意 | [調べる範囲](#共通設定とroi)。省略時は画像全体。 |

画像のおおまかな特徴を64ビットのハッシュにし、異なるビットが少ないほどスコアが高くなります。

入力と参照画像は8ビットカラーを使います。参照画像に透過部分がある場合は、参照画像と調べる範囲の寸法を合わせます。細部が異なる画像でもスコアが1になる場合があります。

## difference_hash_similarity

大きさが違う画像や、カラーとグレースケールの画像で、横方向の明暗の並びを比べる場合に使います。

```yaml
type: difference_hash_similarity
reference: images/screen.png
hash_size: 8
```

| 設定項目 | 必須・任意 | 指定する値 |
| --- | --- | --- |
| `reference` | 必須 | [参照画像](#参照画像とチャンネル)のパス。 |
| `hash_size` | 任意 | 正の整数。既定値は `8`。 |
| `roi` | 任意 | [調べる範囲](#共通設定とroi)。省略時は画像全体。 |

横に隣り合う画素のどちらが明るいかをハッシュにします。異なるビットが少ないほどスコアが高くなります。

`hash_size` を大きくすると細部を比較できますが、計算量も増えます。参照画像のalphaはマスクに使いません。異なる画像でもスコアが1になる場合があります。

## mean_brightness

フェードなど、画面や領域の明暗の変化を調べる場合に使います。

```yaml
type: mean_brightness
roi: {x: 0, y: 0, width: 100, height: 100}
```

| 設定項目 | 必須・任意 | 指定する値 |
| --- | --- | --- |
| `roi` | 任意 | [調べる範囲](#共通設定とroi)。省略時は画像全体。 |

調べる範囲の画素の全チャンネルを同じ重みで平均します。通常の8ビット入力では黒が0、白が1です。

BGRA画像ではalphaも平均に含まれます。通常のNDI入力では判定前にalphaが取り除かれます。しきい値より暗いことを条件にするには、`detected` を `not` と組み合わせます。

## color_range

単色の表示や、画面に重ねた色がどの程度映っているかを調べる場合に使います。

```yaml
type: color_range
lower: [0, 0, 180]
upper: [80, 80, 255]
```

| 設定項目 | 必須・任意 | 指定する値 |
| --- | --- | --- |
| `lower` | 必須 | チャンネルごとの下限。 |
| `upper` | 必須 | チャンネルごとの上限。 |
| `roi` | 任意 | [調べる範囲](#共通設定とroi)。省略時は画像全体。 |

すべてのチャンネルで下限以上、上限以下の画素を数え、調べた全画素に対する割合を返します。例では主に赤い画素を数えます。

上下限には、グレースケールなら1成分、カラーならB、G、Rの順に3成分を指定します。各成分の下限は上限以下にし、NaNや無限大は使えません。通常の映像は0〜255ですが、設定値はこの範囲に限定されません。

## phase_correlation

同じ大きさの画像で、模様の位置がずれる場合に使います。

```yaml
type: phase_correlation
reference: images/screen.png
```

| 設定項目 | 必須・任意 | 指定する値 |
| --- | --- | --- |
| `reference` | 必須 | [参照画像](#参照画像とチャンネル)のパス。 |
| `roi` | 任意 | [調べる範囲](#共通設定とroi)。省略時は画像全体。 |

グレースケールに変換し、平行移動に対応する相関のピークの強さをスコアにします。Conditionで使えるのは相関のスコアです。

参照画像と調べる範囲の寸法を合わせます。参照画像のalphaはマスクに使いません。一様な画像や、同じ模様が繰り返し現れて対応位置が曖昧な画像には向きません。

## 参照画像とチャンネル

参照画像の相対パスは[YAMLの保存場所](yaml-reference.md#パス)を基準にします。通常は8ビットのカラーPNGを用意してください。読み込み時に、チャンネル数やビット深度を一律には変換しません。

チャンネルは画素を構成する色などの成分です。グレースケールは1チャンネル、BGRは青・緑・赤の3チャンネル、BGRAはそれに透明度のalphaを加えた4チャンネルです。グレースケールPNGを読み込んでも、自動でカラーのBGR画像にはなりません。

参照画像として読み込めるのは、1チャンネルのグレースケール、3チャンネルのBGR、4チャンネルのBGRAです。ただし、判定方法によって、さらに制約があります。

BGRAのalphaには、完全に透明な0か、完全に不透明な255だけを使ってください。半透明のピクセルがある画像や、すべて透明な画像は使えません。すべて不透明ならalphaを取り除き、マスクなしの画像として扱います。一部が透明な画像では、方式ごとに次のように扱います。

| Detector | 入力と参照画像の寸法・チャンネル | 透過ピクセルの扱い |
| --- | --- | --- |
| `template_match` | 参照の幅・高さは領域以下。alpha除去後のチャンネル数が一致すること。 | 二値マスクで相関を計算。 |
| `mean_absolute_similarity`、`root_mean_square_similarity` | 幅・高さと、alpha除去後のチャンネル数が完全一致。 | 誤差と成分数から除外。 |
| `histogram_similarity`、`perceptual_hash_similarity` | 入力は8ビットBGR、参照は8ビットBGR／BGRA。マスクなしなら寸法が異なってもよく、ありなら領域と完全一致。 | histogramは除外し、perceptual hashは両画像の同じ位置を黒にする。 |
| `difference_hash_similarity` | 寸法の違いとグレースケール／BGR／BGRAを許容し、グレースケールへ変換。 | alphaを検証して除くが、マスクは使わない。 |
| `phase_correlation` | 幅・高さが完全一致。グレースケール／BGR／BGRAを浮動小数点グレースケールへ変換。 | alphaを検証して除くが、マスクは使わない。 |

`template_match` と画素ごとの誤差を比べる方式では、BGRの入力映像にはBGRの参照画像を使ってください。

画素の誤差を比べる方式は255を基準にスコアを求めるため、参照画像には8ビットが適しています。`template_match` は計算に使える8ビットまたは浮動小数点の画像に変換しますが、16ビットの画素値を0～255の範囲へ変換する処理は行いません。

`histogram_similarity` と `perceptual_hash_similarity` では、8ビット以外の参照画像を使えません。`difference_hash_similarity` と `phase_correlation` は浮動小数点のグレースケールに変換して比較します。空の画像や、形式が条件に合わない画像は、読み込み時または判定時のエラーになります。

Profileの [`resize_references`](../configuration.md#cropresize参照画像) を有効にしている場合は、読み込み時に参照画像の寸法が変わります。Applyで参照画像自体は検証しますが、ROIの範囲や、実際の映像と寸法・チャンネルが合うかを確認するには、映像のフレームが必要です。

## スコアの計算

`clamp` は値を0〜1の範囲に収める処理です。画素の誤差を計算するときは、入力と参照の成分ごとの差を `d_i`、比較した成分数を `N` とします。

| Detector | スコアの求め方 |
| --- | --- |
| `template_match` | マスクなしではOpenCVの `TM_CCOEFF_NORMED` を使います。チャンネルごとの平均を差し引いて求めた最大相関を `r` とすると、スコアは `clamp((r + 1) / 2)` です。相関0はスコア0.5に相当します。マスクありでは `TM_CCORR_NORMED` を使い、最大相関をそのまま `clamp` します。相関がNaNまたは無限大の場合は判定エラーになります。 |
| `mean_absolute_similarity` | `clamp(1 - (sum(abs(d_i)) / N) / 255)` |
| `root_mean_square_similarity` | `clamp(1 - sqrt(sum(d_i * d_i) / N) / 255)` |
| `histogram_similarity` | 色ごとに8区分、計512区分のRGB結合ヒストグラムをL2正規化します。Bhattacharyya距離を `D` とすると、スコアは `clamp(1 - D)` です。 |
| `perceptual_hash_similarity` | マスクの透明部分を両画像とも黒にし、area補間で8×8に変換した画像をexact linear補間で32×32に拡大します。グレースケールに変換してDCTを行い、左上8×8の係数から64ビットのハッシュを求めます。DC成分を0にし、平均より大きい係数のビットを立てます。スコアは `clamp(1 - HammingDistance / 64)` です。 |
| `difference_hash_similarity` | 浮動小数点のグレースケール画像をarea補間で `(hash_size + 1) × hash_size` に変換します。右の画素が左より明るければビットを立てます。スコアは `clamp(1 - differing_bits / hash_size²)` です。 |
| `mean_brightness` | 全画素の全成分の平均を255で割り、`clamp` します。 |
| `color_range` | 指定範囲内の画素数を、調べた範囲の全画素数で割ります。 |
| `phase_correlation` | 浮動小数点のグレースケール画像にOpenCVの `phaseCorrelate` を窓指定なしで適用し、相関ピークの強さを示すresponseを `clamp` します。responseがNaNまたは無限大の場合は判定エラーになります。 |
