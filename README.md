# myrecorder

高并发直播录制服务：轮询开播状态 -> 解析 m3u8 -> `streamlink` 直写 `ts` -> 元数据落 SQLite。

## 最小配置

只需要两个文件：

1. `config.yaml`：服务参数  
2. `streams.yaml`：直播主页/流地址列表

### `streams.yaml`

```yaml
streams:
  - https://nicochannel.jp/your_channel/
  - https://example.com/path/live.m3u8
```

### `config.yaml`

```yaml
service:
  poller_concurrency: 200
  recorder_concurrency: 40
  output_dir: ./recordings
  metadata_db: ./data/metadata.db
  output_format: ts
  streamlink_path: streamlink
  streamlink_quality: best
  streamlink_log_dir: ./logs/streamlink
  default_check_interval_seconds: 12
```

说明：
- provider 自动识别：`nicochannel.jp -> nicochannel`，`.m3u8 -> direct_m3u8`。
- Nico 默认参数内置为：`quality=best, timeout=5, retries=3`。

## 可选：provider 覆写

默认不需要写。只有要覆写时再在 `config.yaml` 添加：

```yaml
provider_defaults:
  base:
    quality: best
    timeout: 5
    retries: 3
  providers:
    nicochannel:
      quality: 720p
```

## 运行

```bash
python run.py -c config.yaml -s streams.yaml
```

## 输出

- 录制文件：`recordings/<provider>/<streamer>/<timestamp>_<title>_<session>.ts`
- 应用日志：`logs/debug.log`
- 录制 stderr：`logs/streamlink/<provider>/<target>_<session>.log`
- 元数据库：`data/metadata.db`
