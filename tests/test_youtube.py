import logging
from unittest.mock import MagicMock

from yt.youtube import YouTube

logger = logging.getLogger("test")


def fake_stream(filesize: int) -> MagicMock:
    stream = MagicMock()
    stream.filesize = filesize
    stream.width = 1280
    stream.height = 720
    stream.url = "https://youtube/stream"
    stream.iter_chunks.return_value = [b"x" * 16, b"y" * 16]
    return stream


def patch_ytube(monkeypatch, streams):
    def factory(url):
        yt = MagicMock()
        yt.length = 215
        yt.title = "Video title"
        yt.streams.filter.return_value.order_by.return_value.desc.return_value = streams
        return yt

    monkeypatch.setattr("yt.youtube.YTube", factory)


def test_downloads_first_stream_under_limit(monkeypatch):
    stream = fake_stream(10)
    patch_ytube(monkeypatch, [fake_stream(1000), stream])
    yt = YouTube(logger, limit=500)
    media = yt.get_media("https://youtu.be/abc")
    assert len(media.videos) == 1
    video = media.videos[0]
    assert (video.duration, video.width, video.height) == (215, 1280, 720)
    assert media.caption == "Video title"
    # The temp file holds the streamed bytes
    assert video.source.read() == b"x" * 16 + b"y" * 16
    # pytubefix's default range size is kept (a chunk size would change it module-wide)
    stream.iter_chunks.assert_called_once_with()


def test_no_stream_under_limit_returns_empty(monkeypatch):
    patch_ytube(monkeypatch, [fake_stream(1000), fake_stream(2000)])
    yt = YouTube(logger, limit=500)
    media = yt.get_media("https://youtu.be/abc")
    assert media.videos == []
