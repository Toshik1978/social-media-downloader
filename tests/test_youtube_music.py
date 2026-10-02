import logging
from unittest.mock import MagicMock

from yt.youtube_music import YouTubeMusic

logger = logging.getLogger("test")

URL = "https://music.youtube.com/watch?v=abc"


def fake_stream(filesize: int) -> MagicMock:
    stream = MagicMock()
    stream.filesize = filesize
    stream.url = "https://youtube/audio"
    stream.iter_chunks.return_value = [b"x" * 16, b"y" * 16]
    return stream


def patch_ytube(monkeypatch, stream, author="Artist - Topic"):
    def factory(url):
        yt = MagicMock()
        yt.title = "Song"
        yt.author = author
        yt.length = 215
        yt.streams.get_audio_only.return_value = stream
        return yt

    monkeypatch.setattr("yt.youtube_music.YTube", factory)


def test_downloads_audio_with_metadata(monkeypatch):
    stream = fake_stream(100)
    patch_ytube(monkeypatch, stream)
    media = YouTubeMusic(logger, limit=500).get_media(URL)

    assert len(media.audios) == 1
    audio = media.audios[0]
    assert (audio.title, audio.performer, audio.duration) == ("Song", "Artist", 215)
    # The temp file holds the streamed bytes
    assert audio.file.read() == b"x" * 16 + b"y" * 16
    # pytubefix's default range size is kept (a chunk size would change it module-wide)
    stream.iter_chunks.assert_called_once_with()
    assert media.videos == []
    # Title and performer are shown by the audio player, no caption needed
    assert media.caption is None


def test_keeps_regular_channel_name(monkeypatch):
    patch_ytube(monkeypatch, fake_stream(100), author="Some Channel")
    media = YouTubeMusic(logger, limit=500).get_media(URL)
    assert media.audios[0].performer == "Some Channel"


def test_no_audio_stream_returns_empty(monkeypatch):
    patch_ytube(monkeypatch, None)
    media = YouTubeMusic(logger, limit=500).get_media(URL)
    assert media.audios == []


def test_audio_over_limit_returns_empty(monkeypatch):
    stream = fake_stream(500)
    patch_ytube(monkeypatch, stream)
    media = YouTubeMusic(logger, limit=500).get_media(URL)
    assert media.audios == []
    stream.iter_chunks.assert_not_called()
