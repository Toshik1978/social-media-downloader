import io
import logging
from unittest.mock import MagicMock

import pytest

from yt.youtube import YouTube

logger = logging.getLogger("test")


def fake_stream(
    filesize: int, *, resolution: int = 720, codec: str = "avc1.4d401f", chunks=(b"x" * 16, b"y" * 16)
) -> MagicMock:
    stream = MagicMock()
    stream.filesize = filesize
    stream.width = resolution * 16 // 9
    stream.height = resolution
    stream.resolution = f"{resolution}p"
    stream.video_codec = codec
    stream.abr = "128kbps"
    stream.url = "https://youtube/stream"
    stream.iter_chunks.return_value = list(chunks)
    return stream


def patch_ytube(monkeypatch, *, progressive=(), adaptive=(), audio=None, length=215) -> list[dict]:
    """Fake pytubefix.YouTube; returns the kwargs of every streams.filter() call."""
    queries = []

    def factory(url):
        yt = MagicMock()
        yt.length = length
        yt.title = "Video title"

        def filter_(**kwargs):
            queries.append(kwargs)
            query = MagicMock()
            query.order_by.return_value.desc.return_value = list(adaptive if kwargs.get("adaptive") else progressive)
            return query

        yt.streams.filter.side_effect = filter_
        yt.streams.get_audio_only.return_value = audio
        return yt

    monkeypatch.setattr("yt.youtube.YTube", factory)
    return queries


def patch_ffmpeg(monkeypatch, *, available=True) -> list[tuple]:
    """Stub media.ffmpeg; mux/transcode record the contents of the files they get."""
    calls = []
    monkeypatch.setattr("media.ffmpeg.available", lambda: available)

    def read(path):
        with open(path, "rb") as f:
            return f.read()

    def fake_mux(video_path, audio_path):
        calls.append(("mux", read(video_path), read(audio_path)))
        return io.BytesIO(b"muxed")

    def fake_transcode(inputs, duration, limit):
        calls.append(("transcode", *[read(path) for path in inputs], duration, limit))
        return io.BytesIO(b"transcoded")

    monkeypatch.setattr("media.ffmpeg.mux", fake_mux)
    monkeypatch.setattr("media.ffmpeg.transcode", fake_transcode)
    return calls


# --- without ffmpeg: progressive streams, as before ---------------------------


def test_without_ffmpeg_downloads_first_progressive_stream_under_limit(monkeypatch):
    patch_ffmpeg(monkeypatch, available=False)
    stream = fake_stream(10)
    queries = patch_ytube(monkeypatch, progressive=[fake_stream(1000), stream])
    media = YouTube(logger, limit=500).get_media("https://youtu.be/abc")
    assert queries == [{"progressive": True}]
    assert len(media.videos) == 1
    video = media.videos[0]
    assert (video.duration, video.width, video.height) == (215, 1280, 720)
    assert media.caption == "Video title"
    # The temp file holds the streamed bytes
    assert video.source.read() == b"x" * 16 + b"y" * 16
    # pytubefix's default range size is kept (a chunk size would change it module-wide)
    stream.iter_chunks.assert_called_once_with()


def test_without_ffmpeg_no_progressive_stream_under_limit_returns_empty(monkeypatch):
    patch_ffmpeg(monkeypatch, available=False)
    patch_ytube(monkeypatch, progressive=[fake_stream(1000), fake_stream(2000)])
    assert YouTube(logger, limit=500).get_media("https://youtu.be/abc").videos == []


# --- with ffmpeg: adaptive H.264 + audio ---------------------------------------


def test_joins_best_h264_video_and_audio_that_fit(monkeypatch):
    calls = patch_ffmpeg(monkeypatch)
    adaptive = [
        fake_stream(300, resolution=1080, codec="av01.0.08M.08", chunks=(b"av1",)),  # fits, but AV1
        fake_stream(450, resolution=1080, chunks=(b"1080",)),  # too big together with the audio
        fake_stream(350, resolution=720, chunks=(b"720",)),
        fake_stream(100, resolution=480, chunks=(b"480",)),
    ]
    queries = patch_ytube(monkeypatch, adaptive=adaptive, audio=fake_stream(100, chunks=(b"audio",)))
    media = YouTube(logger, limit=500).get_media("https://youtu.be/abc")

    assert queries == [{"adaptive": True, "only_video": True, "file_extension": "mp4"}]
    assert calls == [("mux", b"720", b"audio")]
    video = media.videos[0]
    assert (video.source.read(), video.duration, video.width, video.height) == (b"muxed", 215, 1280, 720)
    assert media.caption == "Video title"


@pytest.mark.parametrize(
    "resolutions, chosen",
    [
        ([1080, 720, 480], b"720"),  # the re-encode caps at 720p: no need to download 1080p
        ([2160, 1080], b"1080"),  # nothing at or below 720p: the lowest one
    ],
)
def test_compresses_when_no_pair_fits(monkeypatch, resolutions, chosen):
    calls = patch_ffmpeg(monkeypatch)
    adaptive = [fake_stream(60_000_000, resolution=r, chunks=(str(r).encode(),)) for r in resolutions]
    audio = fake_stream(4_000_000, chunks=(b"audio",))
    patch_ytube(monkeypatch, adaptive=adaptive, audio=audio, length=262)
    media = YouTube(logger, limit=50_000_000).get_media("https://youtu.be/abc")

    assert calls == [("transcode", chosen, b"audio", 262, 50_000_000)]
    video = media.videos[0]
    assert (video.source.read(), video.duration) == (b"transcoded", 262)


def test_too_long_to_compress_returns_empty(monkeypatch):
    calls = patch_ffmpeg(monkeypatch)
    patch_ytube(monkeypatch, adaptive=[fake_stream(600_000_000)], audio=fake_stream(50_000_000), length=3600)
    assert YouTube(logger, limit=50_000_000).get_media("https://youtu.be/abc").videos == []
    assert calls == []


def test_compression_failure_returns_empty(monkeypatch):
    patch_ffmpeg(monkeypatch)
    monkeypatch.setattr("media.ffmpeg.transcode", lambda inputs, duration, limit: None)
    patch_ytube(monkeypatch, adaptive=[fake_stream(60_000_000)], audio=fake_stream(4_000_000), length=262)
    assert YouTube(logger, limit=50_000_000).get_media("https://youtu.be/abc").videos == []


def test_download_error_propagates(monkeypatch):
    # e.g. YouTube answering 403 mid-download: the bot logs the adapter error and replies "No media found"
    calls = patch_ffmpeg(monkeypatch)
    video = fake_stream(100)
    video.iter_chunks.side_effect = OSError("HTTP Error 403: Forbidden")
    patch_ytube(monkeypatch, adaptive=[video], audio=fake_stream(100))
    with pytest.raises(OSError):
        YouTube(logger, limit=500).get_media("https://youtu.be/abc")
    assert calls == []


@pytest.mark.parametrize(
    "adaptive, audio",
    [
        ([], fake_stream(1)),  # no video streams
        ([fake_stream(1, codec="vp09.00.40.08")], fake_stream(1)),  # no H.264
        ([fake_stream(1)], None),  # no audio
    ],
)
def test_no_usable_streams_returns_empty(monkeypatch, adaptive, audio):
    calls = patch_ffmpeg(monkeypatch)
    patch_ytube(monkeypatch, adaptive=adaptive, audio=audio)
    assert YouTube(logger, limit=500).get_media("https://youtu.be/abc").videos == []
    assert calls == []
