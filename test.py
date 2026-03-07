from myrecorder.app import load_config
from myrecorder.models import StreamTarget
from myrecorder.uploader import WebDAVUploader

cfg = load_config("config.yaml", "streams.yaml")
uploader = WebDAVUploader(cfg.webdav)
print(cfg.webdav)

target = StreamTarget(
    provider="fc2",
    streamer="upload_test",
    channel_url="https://example.com",
    interval_seconds=20,
)
uploader.upload("test-upload.txt", target)