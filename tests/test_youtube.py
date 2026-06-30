import logging
from unittest.mock import MagicMock

from yt.youtube import YouTube

logger = logging.getLogger("test")


def fake_stream(filesize: int) -> MagicMock:
    stream = MagicMock()
    stream.filesize = filesize
    stream.url = "https://youtube/stream"
    stream.iter_chunks.return_value = [b"x" * 16, b"y" * 16]
    return stream


def patch_ytube(monkeypatch, streams):
    def factory(url):
        yt = MagicMock()
        yt.streams.filter.return_value.order_by.return_value.desc.return_value = streams
        return yt

    monkeypatch.setattr("yt.youtube.YTube", factory)


def test_downloads_first_stream_under_limit(monkeypatch):
    patch_ytube(monkeypatch, [fake_stream(1000), fake_stream(10)])
    yt = YouTube(logger, limit=500)
    media = yt.get_media("https://youtu.be/abc")
    assert len(media.video_files) == 1
    # The temp file holds the streamed bytes
    f = media.video_files[0]
    f.seek(0)
    assert f.read() == b"x" * 16 + b"y" * 16


def test_no_stream_under_limit_returns_empty(monkeypatch):
    patch_ytube(monkeypatch, [fake_stream(1000), fake_stream(2000)])
    yt = YouTube(logger, limit=500)
    media = yt.get_media("https://youtu.be/abc")
    assert media.video_files == []
    assert media.video_urls == []
