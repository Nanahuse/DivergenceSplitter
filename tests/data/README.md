# 動画デコーダーのフォールバック用テストデータ

`fallback-h264.mp4` は、テストのために生成した灰色の動画です。寸法は128×128、長さは2フレームで、H.264のbaselineプロファイルを使っています。第三者の映像素材は含みません。

Windowsの入力ソースの回帰テストで使います。内蔵MJPEGリーダーで開けない動画を、Windowsのデコーダーで開き直せることを確認するためのファイルです。テストを実行する環境にFFmpegをインストールする必要はありません。

生成には次のコマンドを使いました。

```sh
ffmpeg -f lavfi -i color=gray:s=128x128:r=30 -frames:v 2 -c:v libx264 -profile:v baseline -pix_fmt yuv420p fallback-h264.mp4
```
