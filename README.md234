# myrecorder

NicoChannel + FC2 multi-stream watcher/downloader.

Features:
- Wait while offline, auto start downloading when live starts
- Save metadata via `--write-info-json`
- Monitor multiple streamers in parallel
- `providers` use one unified interface in app
- Provider can be auto-detected from URL (`nicochannel.jp` / `live.fc2.com`)
- Use `yt_dlp` Python API (no yt-dlp executable subprocess)

## Config

`config.yaml`:

```yaml
service:
  output_dir: ./recordings
  poll_interval_seconds: 20
  request_timeout_seconds: 8
  request_retries: 3
  live_from_start: true
  write_info_json: true
  hls_use_mpegts: true
  wait_for_video: 20-60
  ytdlp_extra_args: []
```

`ytdlp_format` is optional. If omitted, no `-f` is passed to yt-dlp.
`ytdlp_extra_args` is not supported in Python API mode.

`streams.yaml`:

```yaml
streams:
  - streamer: uraopkigesakuch
    channel_url: https://nicochannel.jp/uraopkigesakuch/

  - streamer: fc2_example
    channel_url: https://live.fc2.com/12345678/
    wait_for_video: 15-45
```

`provider` field is optional; if omitted, it is inferred from `channel_url`.

## Run

```bash
python run.py -c config.yaml -s streams.yaml
```

## Output

- Video files: `recordings/<streamer>/*`
- Metadata: `recordings/<streamer>/*.info.json`
- Archive file: `recordings/.download-archive.txt`

