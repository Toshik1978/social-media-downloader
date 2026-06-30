from logging import Logger
from tempfile import TemporaryFile
from urllib.parse import urlparse

from pytubefix import Stream
from pytubefix import YouTube as YTube

from media.media import Medias, SocialMedia


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
        return parsed_url.scheme in ["http", "https"] and (
            parsed_url.netloc.endswith("youtube.com") or parsed_url.netloc.endswith("youtu.be")
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
                return self.__download_stream(stream)

        self.__logger.info(f"Didn't find an acceptable stream: {url}")
        return Medias([], [], [], [])

    def __download_stream(self, stream: Stream) -> Medias:
        self.__logger.info(f"Downloading {stream.url}")

        f = TemporaryFile()
        f.writelines(stream.iter_chunks(262144))
        f.seek(0)
        return Medias([], [], [], [f])
