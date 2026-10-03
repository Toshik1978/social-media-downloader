import io
import subprocess
import threading

import pytest

from media import ffmpeg

requires_ffmpeg = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg is not installed")


def make_clip(path, *, video: str | None = "1280x720", audio: bool = True, seconds: int = 3) -> str:
    """Generate a tiny test clip with ffmpeg's lavfi sources."""
    args = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
    if video:
        args += ["-f", "lavfi", "-i", f"testsrc=size={video}:rate=25:duration={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    if video:
        args += ["-c:v", "libx264"]
    if audio:
        args += ["-c:a", "aac"]
    subprocess.run([*args, str(path)], check=True, capture_output=True)
    return str(path)


def probe(f) -> tuple[list[str], tuple[int, int] | None]:
    """Stream types and video size of an open file, via ffprobe on /dev/fd."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "csv=p=0", "-"],
        stdin=f,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    kinds, size = [], None
    for line in out:
        kind, *rest = line.split(",")
        kinds.append(kind)
        if kind == "video":
            size = (int(rest[0]), int(rest[1]))
    return kinds, size


# --- available / video_bitrate ---------------------------------------------


@pytest.mark.parametrize("which, expected", [({"ffmpeg", "ffprobe"}, True), ({"ffmpeg"}, False), (set(), False)])
def test_available(monkeypatch, which, expected):
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda name: f"/usr/bin/{name}" if name in which else None)
    assert ffmpeg.available() is expected


@pytest.mark.parametrize(
    "duration, expected",
    [
        (262, 1_322_381),  # the 4m22s tweet from the bug report: comfortably 720p
        (400, 822_000),
        (605, 500_099),  # just above the floor (~10 min for 50 MB)
        (606, None),  # just below it
        (3600, None),
        (0, None),
    ],
)
def test_video_bitrate(duration, expected):
    assert ffmpeg.video_bitrate(duration, 50_000_000) == expected


# --- duration ----------------------------------------------------------------


@requires_ffmpeg
def test_duration_of_real_clip(tmp_path):
    assert ffmpeg.duration(make_clip(tmp_path / "clip.mp4")) == 3


@pytest.mark.parametrize(
    "outcome",
    [
        subprocess.TimeoutExpired("ffprobe", 60),
        subprocess.CalledProcessError(1, "ffprobe"),
        FileNotFoundError("ffprobe"),
        "N/A\n",
        "0.2\n",
    ],
)
def test_duration_unknown(monkeypatch, outcome):
    def fake_run(*args, **kwargs):
        if isinstance(outcome, BaseException):
            raise outcome
        return subprocess.CompletedProcess(args, 0, stdout=outcome)

    monkeypatch.setattr(ffmpeg.subprocess, "run", fake_run)
    assert ffmpeg.duration("http://v/1.mp4") is None


# --- mux ---------------------------------------------------------------------


@requires_ffmpeg
def test_mux_joins_video_and_audio(tmp_path):
    video = make_clip(tmp_path / "v.mp4", video="640x360", audio=False)
    audio = make_clip(tmp_path / "a.m4a", video=None, audio=True)
    with ffmpeg.mux(video, audio) as f:
        assert probe(f) == (["video", "audio"], (640, 360))


@requires_ffmpeg
def test_mux_failure_raises(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        ffmpeg.mux(str(tmp_path / "missing.mp4"), str(tmp_path / "missing.m4a"))


# --- transcode ---------------------------------------------------------------


@requires_ffmpeg
def test_transcode_fits_limit(tmp_path):
    clip = make_clip(tmp_path / "clip.mp4", video="1920x1080")
    with ffmpeg.transcode([clip], 3, 1_000_000) as f:
        assert f.seek(0, io.SEEK_END) <= 1_000_000
        f.seek(0)
        # 2.4 Mbps is HD: the 1080p source is scaled down to 720p
        assert probe(f) == (["video", "audio"], (1280, 720))


@requires_ffmpeg
def test_transcode_separate_video_and_audio(tmp_path):
    video = make_clip(tmp_path / "v.mp4", video="640x360", audio=False)
    audio = make_clip(tmp_path / "a.m4a", video=None, audio=True)
    with ffmpeg.transcode([video, audio], 3, 1_000_000) as f:
        # Never upscaled
        assert probe(f) == (["video", "audio"], (640, 360))


@requires_ffmpeg
def test_transcode_video_without_audio(tmp_path):
    clip = make_clip(tmp_path / "clip.mp4", video="640x360", audio=False)
    with ffmpeg.transcode([clip], 3, 1_000_000) as f:
        assert probe(f) == (["video"], (640, 360))


def test_transcode_below_floor_does_not_run(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("ffmpeg must not run")

    monkeypatch.setattr(ffmpeg, "_run_to_file", fail)
    assert ffmpeg.transcode(["http://v/1.mp4"], 3600, 50_000_000) is None


@pytest.mark.parametrize("duration, height", [(262, 720), (400, 480)])
def test_transcode_command_line(monkeypatch, duration, height):
    calls = []

    def fake_run_to_file(args, timeout):
        calls.append((args, timeout))
        return io.BytesIO(b"x")

    monkeypatch.setattr(ffmpeg, "_run_to_file", fake_run_to_file)
    f = ffmpeg.transcode(["http://v/1.mp4"], duration, 50_000_000)
    assert f.read() == b"x"

    ((args, timeout),) = calls
    bitrate = str(ffmpeg.video_bitrate(duration, 50_000_000))
    assert timeout == ffmpeg.TRANSCODE_TIMEOUT
    assert args[:2] == ["-i", "http://v/1.mp4"]
    assert ["-map", "0:v:0", "-map", "0:a:0?"] == args[2:6]
    assert args[args.index("-vf") + 1] == (
        f"scale='if(gte(iw,ih),-2,min(iw,{height}))':'if(gte(iw,ih),min(ih,{height}),-2)'"
    )
    assert args[args.index("-b:v") + 1] == bitrate
    assert args[args.index("-maxrate") + 1] == bitrate
    assert args[args.index("-bufsize") + 1] == str(2 * int(bitrate))
    assert args[args.index("-b:a") + 1] == str(ffmpeg.AUDIO_BITRATE)


def test_transcode_two_inputs_maps_audio_from_second(monkeypatch):
    calls = []
    monkeypatch.setattr(ffmpeg, "_run_to_file", lambda args, timeout: calls.append(args) or io.BytesIO(b"x"))
    ffmpeg.transcode(["v.mp4", "a.m4a"], 262, 50_000_000)
    assert calls[0][:8] == ["-i", "v.mp4", "-i", "a.m4a", "-map", "0:v:0", "-map", "1:a:0?"]


def test_transcode_output_within_limit_is_rewound(monkeypatch):
    out = io.BytesIO(b"x" * 100_000)
    out.seek(0, io.SEEK_END)
    monkeypatch.setattr(ffmpeg, "_run_to_file", lambda args, timeout: out)
    # 1 s in 100 kB allows 632 kbps of video: above the floor, so ffmpeg runs
    f = ffmpeg.transcode(["http://v/1.mp4"], 1, 100_000)
    assert f is out and f.tell() == 0


def test_transcode_output_over_limit_is_dropped(monkeypatch):
    out = io.BytesIO(b"x" * 100_001)
    monkeypatch.setattr(ffmpeg, "_run_to_file", lambda args, timeout: out)
    assert ffmpeg.transcode(["http://v/1.mp4"], 1, 100_000) is None
    assert out.closed


def test_transcodes_run_one_at_a_time(monkeypatch):
    started = threading.Event()
    monkeypatch.setattr(ffmpeg, "_run_to_file", lambda args, timeout: started.set() or io.BytesIO(b"x"))
    with ffmpeg._transcode_lock:
        worker = threading.Thread(target=ffmpeg.transcode, args=(["http://v/1.mp4"], 262, 50_000_000))
        worker.start()
        # Another re-encode is running: this one waits for it
        assert not started.wait(0.2)
    worker.join(5)
    assert started.is_set()


@pytest.mark.parametrize(
    "error",
    [
        subprocess.CalledProcessError(1, "ffmpeg", stderr=b"boom"),
        subprocess.TimeoutExpired("ffmpeg", 600),
        FileNotFoundError("ffmpeg"),
    ],
)
def test_transcode_failure_returns_none(monkeypatch, error):
    def fail(args, timeout):
        raise error

    monkeypatch.setattr(ffmpeg, "_run_to_file", fail)
    assert ffmpeg.transcode(["http://v/1.mp4"], 262, 50_000_000) is None
