# myrecorder

高并发直播录制服务：轮询直播状态 -> 获取 m3u8 -> 用 `streamlink` 直写 `ts` -> 记录元数据到 SQLite。

## 当前实现概览

- 录制后端：`streamlink`（不转码，源流直写）
- 调度模型：`asyncio` 轮询 + 并发限制 + 失败退避
- 平台接入：`providers` 机制（统一 `check_live()` 协议）
- 元数据：SQLite（WAL）+ 异步写队列

核心模块：
- `myrecorder/scheduler.py`：轮询与状态机
- `myrecorder/recorder.py`：录制进程管理
- `myrecorder/providers/`：平台 provider 实现
- `myrecorder/provider_registry.py`：provider 注册
- `myrecorder/storage.py`：元数据落盘

## 已支持 provider

- `nicochannel`
- `direct_m3u8`
- `json_api`
- `mock`

说明：

## 配置文件

项目当前使用两个文件：

1. `config.yaml`：系统参数 + `providers_defaults`
2. `streams.yaml`：直播链接列表

### streams.yaml

```yaml
streams:
  - https://nicochannel.jp/your_channel_1/
  - https://nicochannel.jp/your_channel_2/
  - https://example.com/live/xxx.m3u8
```

### config.yaml（关键项）

- `service.poller_concurrency`：状态检测并发
- `service.recorder_concurrency`：录制并发
- `service.streamlink_path`：`streamlink` 可执行文件
- `service.streamlink_quality`：默认画质（如 `best`）
- `service.output_format`：当前仅支持 `ts`

自动识别规则：
- 域名包含 `nicochannel.jp` -> `nicochannel`
- URL 包含 `.m3u8` -> `direct_m3u8`

## 运行

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -e .
python run.py -c config.yaml -s streams.yaml
```

也可用：
```bash
myrecorder -c config.yaml -s streams.yaml
```

## 输出与日志

- 录制文件：`recordings/<provider>/<streamer>/<timestamp>_<title>_<session>.ts`
- 应用日志：`logs/debug.log`
- 每路录制 stderr：`logs/streamlink/<provider>/<target>_<session>.log`
- 元数据库：`data/metadata.db`

数据库主要表：
- `targets`
- `sessions`
- `events`

## 常见问题

1. `streamlink` 命令找不到  
确保 `streamlink --version` 可执行，或在 `config.yaml` 设置 `service.streamlink_path`。

2. 录制文件不增长  
先看对应 `logs/streamlink/...log`，确认是否源流断开或鉴权失效。

3. provider 名称不识别  
检查 `myrecorder/provider_registry.py` 是否注册，及配置里的 `providers/providers_defaults` 拼写。

## 扩展新 provider

1. 在 `myrecorder/providers/` 新增 provider 类，实现 `check_live(target, http) -> LiveInfo`
2. 在 `myrecorder/provider_registry.py` 注册
3. 在 `myrecorder/config.py` 的 URL 自动识别逻辑中加入映射
