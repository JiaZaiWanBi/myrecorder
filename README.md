# myrecorder

一个面向直播录制的任务流录播器，目前支持：

- `FC2`
- `NicoChannel`

程序会周期性检查直播状态；检测到开播后，按任务流依次执行各个模块，并把结果保存到本地或上传到远端。

## 功能说明

- 支持多个直播目标并发监听
- 支持根据 `channel_url` 自动识别 provider
- `provider`、`downloader`、`uploader` 都是独立任务模块
- 支持“上一步结果传给下一步任务”
- 支持全局默认任务流、provider 默认任务流、streamer 自定义任务流
- 使用 `yt_dlp` Python API，不依赖 `yt-dlp` 可执行文件
- 支持写出 `info.json`
- 支持可选 WebDAV 上传

## 当前默认任务流

现在运行时的默认任务流是：

```text
provider -> download -> upload
```

其中：

- `provider` 负责探活并产出直播信息
- `download` 负责下载并封装下载结果
- `upload` 负责消费下载结果并上传文件

如果没有配置 `webdav`，默认任务流里的 `upload` 会自动跳过。

## 环境要求

- Python `>= 3.11`
- `ffmpeg`

Windows 下请确认下面命令可用：

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

```powershell
uv run python run.py -c config.yaml -s streams.yaml
```

也可以：

```powershell
uv run python -m myrecorder.app -c config.yaml -s streams.yaml
```

## 配置文件

### `config.yaml`

推荐写法：

```yaml
service:
  output_dir: ./recordings
  interval_seconds: 20
  request_timeout_seconds: 8
  request_retries: 3
  write_info_json: true
  hls_use_mpegts: true
  ytdlp_extra_args: []

  workflow:
    default:
      - download
      - upload
    providers:
      fc2:
        - download
        - upload

webdav:
  url: https://example.com/dav
  user: your-user
  pass: your-password
  root: /myrecorder
  mode: move
```

字段说明：

- `output_dir`: 本地录制输出目录
- `interval_seconds`: 全局轮询间隔
- `request_timeout_seconds`: 网络请求超时
- `request_retries`: 网络请求重试次数
- `ytdlp_format`: 可选，不填则不传格式参数
- `live_from_start`: 可选，默认 `false`
- `write_info_json`: 是否写出 `info.json`
- `hls_use_mpegts`: 是否启用 `mpegts`
- `workflow.default`: 全局默认任务流
- `workflow.providers.<provider>`: 指定 provider 的默认任务流
- `webdav`: 可选；配置后可在任务流中使用上传任务

### `streams.yaml`

`streams.yaml` 顶层直接是列表，程序运行中会自动热加载文件变更。

简写：

```yaml
- streamer: fc2_test1
  channel_url: https://live.fc2.com/75310651/
```

完整写法：

```yaml
- provider: fc2
  streamer: fc2_test1
  channel_url: https://live.fc2.com/75310651/
  interval_seconds: 10

- provider: nicochannel
  streamer: example_nico
  channel_url: https://nicochannel.jp/example_nico/
  workflow:
    - download
```

字段说明：

- `provider`: 可选。不填时根据 `channel_url` 自动识别
- `streamer`: 输出目录名
- `channel_url`: 直播页或频道页地址
- `interval_seconds`: 单个目标自己的轮询间隔
- `downloader`: 可选。指定这个目标要用哪个下载模块
- `workflow`: 可选。为单个 streamer 覆写任务流

## 任务流优先级

任务流会按下面顺序决定：

1. `streams.yaml` 里的单个 `workflow`
2. `config.yaml` 里的 `service.workflow.providers.<provider>`
3. provider 内置默认任务流
4. `config.yaml` 里的 `service.workflow.default`
5. 程序内置默认任务流

## 当前 provider 行为

### FC2

- 通过 `yt_dlp` 提取直播信息并读取 `live_status`
- 开播后进入后续任务流
- 下载时默认不启用 `live_from_start`

### NicoChannel

- 通过 NicoChannel 接口查询直播列表
- 有直播时解析出实际播放地址，再交给下载任务

## 输出文件

默认输出目录由 `config.yaml` 的 `output_dir` 控制。

输出内容通常包括：

- 录制文件：`recordings/<streamer>/*`
- 元信息：`recordings/<streamer>/*.info.json`

## 项目结构

```text
myrecorder/
  app.py                    CLI 入口与配置加载
  models.py                 数据模型与任务抽象
  services.py               watcher 调度
  registry.py               任务注册表
  pipeline.py               任务流构建与执行
  ytdlp_client.py           yt_dlp API 封装
  providers/
    __init__.py             provider 识别与轻量入口
    fc2.py                  FC2 provider 适配器
    nicochannel.py          NicoChannel provider 适配器
  tasks/
    downloaders/
      ytdlp.py              yt-dlp 下载任务
    uploaders/
      webdav.py             WebDAV 上传任务
run.py                      根目录启动脚本
config.yaml                 服务配置示例
streams.yaml                直播目标示例
```

## 已知限制

- 需要系统已安装 `ffmpeg`
- `ytdlp_extra_args` 当前仍要求为空列表
- 当前上传模块只实现了 `webdav`
