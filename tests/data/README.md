# 動画デコーダーのフォールバック用テストデータ

`fallback-h264.mp4` は、テスト用に生成した128×128の灰色の動画です。H.264のbaselineプロファイルで記録した2フレームで、第三者の映像素材は含みません。

Windowsの入力ソースの回帰テストで、内蔵MJPEGリーダーが扱えない入力をWindowsのデコーダーで開けることを確認します。テストの実行時にFFmpegをインストールする必要はありません。

生成には次のコマンドを使いました。

```sh
ffmpeg -f lavfi -i color=gray:s=128x128:r=30 -frames:v 2 -c:v libx264 -profile:v baseline -pix_fmt yuv420p fallback-h264.mp4
```
