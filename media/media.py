from abc import abstractmethod
from dataclasses import dataclass, field
from typing import IO


@dataclass
class Photo:
    """The photo found by URL."""

    url: str
    """Photo URL."""


@dataclass
class Gif:
    """The gif (animation) found by URL."""

    url: str
    """Gif URL."""

    duration: int | None = None
    """Gif duration in seconds."""

    width: int | None = None
    """Gif width."""

    height: int | None = None
    """Gif height."""


@dataclass
class Video:
    """The video found by URL."""

    source: str | IO[bytes]
    """Video URL or downloaded video file."""

    duration: int | None = None
    """Video duration in seconds."""

    width: int | None = None
    """Video width."""

    height: int | None = None
    """Video height."""

    fallbacks: list[str] = field(default_factory=list)
    """Lower-quality URLs of the same video, best first."""


@dataclass
class Audio:
    """The downloaded audio track with its metadata."""

    file: IO[bytes]
    """Audio file."""

    title: str
    """Track title."""

    performer: str
    """Track performer."""

    duration: int
    """Track duration in seconds."""


@dataclass
class Medias:
    """The reference to all media found by URL."""

    album: list[Photo | Video] = field(default_factory=list)
    """Photos and videos sent together as media groups, in order (videos by URL)."""

    gifs: list[Gif] = field(default_factory=list)
    """Gifs."""

    videos: list[Video] = field(default_factory=list)
    """Videos."""

    audios: list[Audio] = field(default_factory=list)
    """Audio tracks."""

    caption: str | None = None
    """Post text (tweet text, Instagram caption, video title)."""


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
