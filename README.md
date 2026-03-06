# myrecorder

一个基于 `yt_dlp` Python API 的直播监听与录制工具，目前支持：

- `FC2`
- `NicoChannel`

程序会周期性检查直播状态，检测到开播后自动开始录制，并把输出保存到 `recordings/<streamer>/` 目录。

## 功能说明

- 支持多个直播目标并发监听
- 支持根据 `channel_url` 自动识别 provider
- 使用 `yt_dlp` Python API，不依赖 `yt-dlp` 可执行文件
- 默认压制 `yt_dlp` / `websockets` / `aiohttp` 等第三方调试日志
- 支持写出 `info.json`
- 支持下载归档，避免重复下载
- FC2 使用 `yt_dlp` 的 `live_status` 探活
- NicoChannel 使用官方接口检查直播状态

## 环境要求

- Python `>= 3.11`
- `ffmpeg`

注意：`uv sync` 只能安装 Python 依赖，不能自动安装系统级 `ffmpeg`。

Windows 下可以自行安装 `ffmpeg`，确认下面命令可用：

```powershell
ffmpeg -version
```

## 安装

推荐使用 `uv`：

```powershell
cd G:\project\myrecorder
uv venv
uv sync
```

## 运行

项目根目录提供了 `run.py`：

```powershell
uv run python run.py -c config.yaml -s streams.yaml
```

也可以直接调用包入口：

```powershell
uv run python -m myrecorder.app -c config.yaml -s streams.yaml
```

## 配置文件

### `config.yaml`

当前代码实际读取的是 `service` 下这些字段：

```yaml
service:
  output_dir: ./recordings
  interval_seconds: 20
  request_timeout_seconds: 8
  request_retries: 3
  # live_from_start: true
  write_info_json: true
  hls_use_mpegts: true
  ytdlp_extra_args: []
```

字段说明：

- `output_dir`: 录制输出目录
- `interval_seconds`: 全局轮询间隔，最小值为 `3`
- `request_timeout_seconds`: 网络请求超时
- `request_retries`: 网络请求重试次数
- `ytdlp_format`: 可选，不填则不传格式参数
- `live_from_start`: 可选，默认 `false`
- `write_info_json`: 是否写出 `info.json`
- `hls_use_mpegts`: 是否启用 `hls_use_mpegts`
- `ytdlp_extra_args`: 当前必须为空列表，当前版本不支持额外参数映射

### `streams.yaml`

```yaml
streams:
  - streamer: fc2_test1
    channel_url: https://live.fc2.com/75310651/
```

也支持更完整的写法：

```yaml
streams:
  - provider: fc2
    streamer: fc2_test1
    channel_url: https://live.fc2.com/75310651/
    interval_seconds: 10

  - provider: nicochannel
    streamer: example_nico
    channel_url: https://nicochannel.jp/example_nico/
```

字段说明：

- `provider`: 可选。不填时会根据 `channel_url` 自动识别
- `streamer`: 输出目录名
- `channel_url`: 直播页或频道页地址
- `interval_seconds`: 单个目标自己的轮询间隔，可覆盖全局设置

## 当前 provider 行为

### FC2

- 通过 `yt_dlp` 提取直播信息并读取 `live_status`
- `is_live` 时开始录制
- 录制时强制不使用 `live_from_start`

### NicoChannel

- 通过 NicoChannel 接口查询直播列表
- 有直播时拼接直播页地址并交给 `yt_dlp`

## 输出文件

默认输出目录由 `config.yaml` 的 `output_dir` 控制。

输出内容通常包括：

- 录制文件：`recordings/<streamer>/*`
- 元信息：`recordings/<streamer>/*.info.json`
- 下载归档：`recordings/.download-archive.txt`

## 日志

- `run.py` 默认会补上 `--log-level DEBUG`
- 程序内部会把 `websockets`、`yt_dlp`、`urllib3`、`aiohttp` 的日志级别压到 `WARNING`
- `yt_dlp` 的 debug/info 输出已经被拦截，主要保留程序自己的日志

如果你不想看 debug 日志，可以显式指定：

```powershell
uv run python run.py --log-level INFO
```

## 项目结构

```text
myrecorder/
  app.py             CLI 入口与配置加载
  models.py          数据模型
  services.py        监听与调度逻辑
  ytdlp_client.py    yt_dlp API 封装
  providers/
    __init__.py      provider 注册与分发
    fc2.py           FC2 探活
    nicochannel.py   NicoChannel 探活
run.py               根目录启动脚本
config.yaml          服务配置
streams.yaml         直播目标列表
```

## 已知限制

- 需要系统已安装 `ffmpeg`
- `ytdlp_extra_args` 当前不支持映射到 Python API，非空会报错
- 当前 README 以仓库内现有代码行为为准，不保证兼容更早版本配置
