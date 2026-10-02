from logging import Logger
from tempfile import TemporaryFile
from typing import IO
from urllib.parse import urlparse

from pytubefix import Stream
from pytubefix import YouTube as YTube

from media.media import Medias, SocialMedia, Video


class YouTube(SocialMedia):
    """YouTube is the class to manage YouTube medias."""

    __logger: Logger
    __limit: int

    def __init__(self, logger: Logger, limit: int):
        self.__logger = logger
        self.__limit = limit

    def is_valid_url(self, url: str) -> bool:
        """Check if URL points to valid social media data."""
        parsed_url = urlparse(url)
        # YouTube Music links are handled by the YouTubeMusic adapter (audio only).
        return (
            parsed_url.scheme in ["http", "https"]
            and parsed_url.netloc != "music.youtube.com"
            and (parsed_url.netloc.endswith("youtube.com") or parsed_url.netloc.endswith("youtu.be"))
        )

    def get_media(self, url: str) -> Medias:
        """Get all available medias."""

        # Get all streams and try to find the best one for the bot needs.
        yt = YTube(url)
        streams = yt.streams.filter(progressive=True).order_by("resolution").desc()
        # Try to fit into limits.
        for stream in streams:
            if stream.filesize < self.__limit:
                # We found the best candidate.
                video = Video(self.__download_stream(stream), yt.length, stream.width, stream.height)
                return Medias(videos=[video], caption=yt.title)

        self.__logger.info(f"Didn't find an acceptable stream: {url}")
        return Medias()

    def __download_stream(self, stream: Stream) -> IO[bytes]:
        self.__logger.info(f"Downloading {stream.url}")

        f = TemporaryFile()
        # No chunk size: pytubefix treats it as the HTTP range size per request (default 9 MB) and sets it
        # module-wide, so a small value means many more requests for every later download too.
        f.writelines(stream.iter_chunks())
        f.seek(0)
        return f
