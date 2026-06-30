from abc import abstractmethod
from tempfile import TemporaryFile


class Medias:
    """The reference to all media found by URL."""

    photo_urls: list[str]
    """Photos URLs."""

    gif_urls: list[str]
    """Gifs URLs."""

    video_urls: list[str]
    """Videos URLs."""

    video_files: list[TemporaryFile]
    """Videos files."""

    def __init__(
        self, photo_urls: list[str], gif_urls: list[str], video_urls: list[str], video_files: list[TemporaryFile]
    ):
        self.photo_urls = photo_urls
        self.gif_urls = gif_urls
        self.video_urls = video_urls
        self.video_files = video_files


class SocialMedia:
    """Base class for social media adapters."""

    @abstractmethod
    def is_valid_url(self, url: str) -> bool:
        """Check if URL points to valid social media data."""
        pass

    @abstractmethod
    def get_media(self, url: str) -> Medias:
        """Get all available medias."""
        pass
