from myrecorder.app import load_config
from myrecorder.models import StreamTarget
from myrecorder.uploader import WebDAVUploader
from myrecorder.ytdlp_client import _upload_outputs, DownloadOptions
from myrecorder.log import configure_logging, get_logger

configure_logging("DEBUG")

cfg = load_config("config.yaml", "streams.yaml")
uploader = WebDAVUploader(cfg.webdav)
target = StreamTarget(
    provider="fc2",
    streamer="fc2_test1",
    channel_url="https://example.com",
    interval_seconds=20,
)

opts = DownloadOptions(
    output_template=r"recordings\fc2_test1\demo.ts",
    ytdlp_format=None,
    live_from_start=False,
    write_info_json=True,
    hls_use_mpegts=True,
    timeout_seconds=8,
    extra_args=[],
)

logger = get_logger(component="watcher", provider="fc2", streamer="fc2_test1")
_upload_outputs(opts.output_template, opts.write_info_json, uploader, target, logger)
