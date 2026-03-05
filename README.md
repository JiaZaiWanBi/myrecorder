# myrecorder

NicoChannel 多主播监听下载器。

功能：
- 轮询主播频道，离线时持续等待开播
- 开播后自动把直播页链接交给 `yt-dlp` 下载
- 使用 `--write-info-json` 保存直播元信息（主播、日期、标题等）
- 同时监听多个主播

## 配置

`config.yaml`:

```yaml
service:
  ytdlp_path: yt-dlp
  ytdlp_format: best
  output_dir: ./recordings
  poll_interval_seconds: 20
  request_timeout_seconds: 8
  request_retries: 3
  live_from_start: true
  write_info_json: true
  ytdlp_extra_args: []
```

`streams.yaml`:

```yaml
streams:
  - https://nicochannel.jp/streamer_a/
  - streamer: streamer_b
    channel_url: https://nicochannel.jp/streamer_b/
    poll_interval_seconds: 15
```

## 运行

```bash
python run.py -c config.yaml -s streams.yaml
```

## 输出

- 视频：`recordings/<streamer>/*.mp4|*.ts...`
- 元信息：`recordings/<streamer>/*.info.json`
- 去重归档：`recordings/.download-archive.txt`
