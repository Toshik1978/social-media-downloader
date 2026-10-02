from logging import Logger
from tempfile import TemporaryFile
from typing import IO
from urllib.parse import urlparse

from pytubefix import Stream
from pytubefix import YouTube as YTube

from media.media import Audio, Medias, SocialMedia


class YouTubeMusic(SocialMedia):
    """YouTubeMusic is the class to manage YouTube Music medias (audio only)."""

    __logger: Logger
    __limit: int

    def __init__(self, logger: Logger, limit: int):
        self.__logger = logger
        self.__limit = limit

    def is_valid_url(self, url: str) -> bool:
        """Check if URL points to valid social media data."""
        parsed_url = urlparse(url)
        return parsed_url.scheme in ["http", "https"] and parsed_url.netloc == "music.youtube.com"

    def get_media(self, url: str) -> Medias:
        """Get all available medias."""

        # The highest bitrate mp4 (AAC/M4A) audio stream, which Telegram plays as a music track.
        yt = YTube(url)
        stream = yt.streams.get_audio_only()
        if stream is None:
            self.__logger.info(f"Didn't find an audio stream: {url}")
            return Medias()
        if stream.filesize >= self.__limit:
            self.__logger.info(f"Audio stream is too large ({stream.filesize}): {url}")
            return Medias()

        # Auto-generated artist channels are named "<Artist> - Topic".
        performer = yt.author.removesuffix(" - Topic")
        return Medias(audios=[Audio(self.__download_stream(stream), yt.title, performer, yt.length)])

    def __download_stream(self, stream: Stream) -> IO[bytes]:
        self.__logger.info(f"Downloading {stream.url}")

        f = TemporaryFile()
        # No chunk size: pytubefix treats it as the HTTP range size per request (default 9 MB) and sets it
        # module-wide, so a small value means many more requests for every later download too.
        f.writelines(stream.iter_chunks())
        f.seek(0)
        return f
