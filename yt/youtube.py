import os
from logging import Logger
from tempfile import TemporaryDirectory, TemporaryFile
from typing import IO
from urllib.parse import urlparse

from pytubefix import Stream
from pytubefix import YouTube as YTube

from media import ffmpeg
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

        yt = YTube(url)
        # Most videos only come as separate video and audio streams, which take ffmpeg to join.
        video = self.__get_adaptive(yt) if ffmpeg.available() else self.__get_progressive(yt)
        if video is None:
            self.__logger.info(f"Didn't find an acceptable stream: {url}")
            return Medias()
        return Medias(videos=[video], caption=yt.title)

    def __get_progressive(self, yt: YTube) -> Video | None:
        # Get all streams and try to find the best one for the bot needs.
        streams = yt.streams.filter(progressive=True).order_by("resolution").desc()
        # Try to fit into limits.
        for stream in streams:
            if stream.filesize < self.__limit:
                # We found the best candidate.
                return Video(self.__download_stream(stream), yt.length, stream.width, stream.height)
        return None

    def __get_adaptive(self, yt: YTube) -> Video | None:
        # H.264 only: not every Telegram client plays AV1 or VP9.
        streams = yt.streams.filter(adaptive=True, only_video=True, file_extension="mp4").order_by("resolution").desc()
        videos = [stream for stream in streams if stream.video_codec.startswith("avc1")]
        # The original-language track: on dubbed videos the best bitrate alone may pick a translation.
        audio = yt.streams.get_default_audio_track().get_audio_only()
        if not videos or audio is None:
            return None

        with TemporaryDirectory() as tmp:
            video_path, audio_path = os.path.join(tmp, "video.mp4"), os.path.join(tmp, "audio.m4a")
            for stream in videos:
                if stream.filesize + audio.filesize < self.__limit:
                    self.__logger.info(f"Joining {stream.resolution} video with {audio.abr} audio")
                    self.__download_to(stream, video_path)
                    self.__download_to(audio, audio_path)
                    return Video(ffmpeg.mux(video_path, audio_path), yt.length, stream.width, stream.height)

            # Nothing fits as is: re-encode, if the video is short enough to still look decent. The re-encode caps
            # at 720p, so start from the best stream at or below that rather than download a bigger one.
            if not yt.length or ffmpeg.video_bitrate(yt.length, self.__limit) is None:
                return None
            stream = next((s for s in videos if min(s.width, s.height) <= 720), videos[-1])
            self.__logger.info(f"Compressing {stream.resolution} video with {audio.abr} audio")
            self.__download_to(stream, video_path)
            self.__download_to(audio, audio_path)
            f = ffmpeg.transcode([video_path, audio_path], yt.length, self.__limit)
            return Video(f, yt.length, stream.width, stream.height) if f is not None else None

    def __download_stream(self, stream: Stream) -> IO[bytes]:
        self.__logger.info(f"Downloading {stream.url}")

        f = TemporaryFile()
        # No chunk size: pytubefix treats it as the HTTP range size per request (default 9 MB) and sets it
        # module-wide, so a small value means many more requests for every later download too.
        f.writelines(stream.iter_chunks())
        f.seek(0)
        return f

    def __download_to(self, stream: Stream, path: str) -> None:
        self.__logger.info(f"Downloading {stream.url}")

        with open(path, "wb") as f:
            # No chunk size, for the same reason as in __download_stream.
            f.writelines(stream.iter_chunks())
