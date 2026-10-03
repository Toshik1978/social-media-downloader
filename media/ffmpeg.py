"""ffmpeg/ffprobe helpers that fit videos into Telegram's upload limit.

Everything here is synchronous and blocks for up to minutes: call it from a worker thread
(`asyncio.to_thread`), never from the event loop.
"""

import logging
import os
import shutil
import subprocess
import threading
from tempfile import TemporaryDirectory
from typing import IO

logger = logging.getLogger(__name__)

AUDIO_BITRATE = 128_000
"""Audio bitrate of a re-encoded video, bit/s."""

MIN_VIDEO_BITRATE = 500_000
"""Below this video bitrate a re-encode looks too bad to be worth it (~10 min for 50 MB)."""

HD_VIDEO_BITRATE = 1_000_000
"""From this video bitrate on, re-encodes keep up to 720p; below it they drop to 480p."""

CONTAINER_MARGIN_PERCENT = 95
"""Share of the size limit given to the streams; the rest absorbs container overhead and bitrate overshoot."""

TRANSCODE_TIMEOUT = 600
"""Seconds a re-encode may take."""

COPY_TIMEOUT = 60
"""Seconds a mux or probe may take."""

_transcode_lock = threading.Lock()
"""Re-encoding is CPU-bound: run one at a time."""


def available() -> bool:
    """Check that ffmpeg and ffprobe are installed."""

    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def video_bitrate(duration: int, limit: int) -> int | None:
    """Video bitrate (bit/s) that fits `duration` seconds into `limit` bytes, or None if it's below the floor."""

    if duration <= 0:
        return None
    bitrate = limit * 8 * CONTAINER_MARGIN_PERCENT // (100 * duration) - AUDIO_BITRATE
    return bitrate if bitrate >= MIN_VIDEO_BITRATE else None


def duration(source: str) -> int | None:
    """Duration in whole seconds of a file or URL, or None if ffprobe can't tell."""

    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", source],
            capture_output=True,
            text=True,
            timeout=COPY_TIMEOUT,
            check=True,
        )
        return round(float(result.stdout)) or None
    except (subprocess.SubprocessError, OSError, ValueError) as e:
        logger.info(f"ffprobe couldn't get the duration: {e.__class__.__qualname__}: {e}")
        return None


def mux(video_path: str, audio_path: str) -> IO[bytes]:
    """Join a video-only and an audio-only file into one MP4 without re-encoding."""

    return _run_to_file(
        ["-i", video_path, "-i", audio_path, "-map", "0:v:0", "-map", "1:a:0", "-c", "copy"], COPY_TIMEOUT
    )


def transcode(inputs: list[str], duration: int, limit: int) -> IO[bytes] | None:
    """Re-encode to an H.264/AAC MP4 of at most `limit` bytes.

    `inputs` is one file or URL with video (and maybe audio), or a video-only and an audio-only one.
    Returns None when the video is too long to look decent in `limit`, ffmpeg fails, or the result is still
    too big.
    """

    if (bitrate := video_bitrate(duration, limit)) is None:
        return None
    # Cap the shorter side, so portrait videos keep their resolution too; never upscale.
    side = 720 if bitrate >= HD_VIDEO_BITRATE else 480
    scale = f"scale='if(gte(iw,ih),-2,min(iw,{side}))':'if(gte(iw,ih),min(ih,{side}),-2)'"
    args = [arg for source in inputs for arg in ("-i", source)]
    args += ["-map", "0:v:0", "-map", f"{len(inputs) - 1}:a:0?", "-vf", scale]
    args += ["-c:v", "libx264", "-preset", "veryfast"]
    args += ["-b:v", str(bitrate), "-maxrate", str(bitrate), "-bufsize", str(2 * bitrate)]
    args += ["-c:a", "aac", "-b:a", str(AUDIO_BITRATE)]
    try:
        with _transcode_lock:
            f = _run_to_file(args, TRANSCODE_TIMEOUT)
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning(f"ffmpeg failed to re-encode: {e.__class__.__qualname__}: {e}")
        return None

    if (size := f.seek(0, os.SEEK_END)) > limit:
        logger.info(f"Re-encoded video is still too large ({size} > {limit})")
        f.close()
        return None
    f.seek(0)
    return f


def _run_to_file(args: list[str], timeout: int) -> IO[bytes]:
    with TemporaryDirectory() as tmp:
        # +faststart rewrites the file, so ffmpeg needs a real (seekable) output path rather than a pipe.
        output = os.path.join(tmp, "output.mp4")
        try:
            subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "error", "-y", *args, "-movflags", "+faststart", output],
                capture_output=True,
                timeout=timeout,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            logger.warning(f"ffmpeg: {e.stderr.decode(errors='replace').strip()}")
            raise
        # The open file outlives the directory (POSIX): the caller gets a temp file that's gone once closed.
        return open(output, "rb")
