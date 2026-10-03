import io
import threading
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
import requests
import telegram.error
from requests.structures import CaseInsensitiveDict
from telegram import constants

from bot.telegram_bot import MEDIA_WRITE_TIMEOUT
from media.media import Audio, Gif, Medias, Photo, SocialMedia, Video
from tests.conftest import make_context, make_update


class FakeAdapter(SocialMedia):
    """Adapter returning a preset Medias (or raising) for the given url(s)."""

    def __init__(self, media: Medias | None = None, valid: bool = True, error: Exception | None = None):
        self._media = media if media is not None else Medias()
        self._valid = valid
        self._error = error

    def is_valid_url(self, url: str) -> bool:
        return self._valid

    def get_media(self, url: str) -> Medias:
        if self._error is not None:
            raise self._error
        return self._media


def fake_response(size: int) -> MagicMock:
    resp = MagicMock()
    resp.headers = CaseInsensitiveDict({"Content-Length": str(size)})
    resp.raise_for_status = MagicMock()
    resp.iter_content = MagicMock(return_value=[b"a" * 8, b"b" * 8])
    return resp


# --- command handlers -------------------------------------------------------


async def test_start_command(bot):
    update, context = make_update(), make_context()
    await bot.start_command_handler(update, context)
    update.effective_message.reply_markdown_v2.assert_awaited_once()


async def test_help_command(bot):
    update, context = make_update(), make_context()
    await bot.help_command_handler(update, context)
    update.effective_message.reply_text.assert_awaited_once()


async def test_stats_initializes_and_reports(bot):
    update, context = make_update(user_id=7), make_context()
    await bot.stats_command_handler(update, context)
    assert context.bot_data["stats"][7] == {"messages_handled": 0, "media_downloaded": 0}
    update.effective_message.reply_markdown_v2.assert_awaited_once()


async def test_resetstats(bot):
    update, context = make_update(user_id=7), make_context()
    context.bot_data["stats"] = {7: {"messages_handled": 5, "media_downloaded": 9}}
    await bot.resetstats_command_handler(update, context)
    assert context.bot_data["stats"][7] == {"messages_handled": 0, "media_downloaded": 0}


# --- download_message_handler ----------------------------------------------


async def test_download_no_media_found(bot):
    bot._SocialMediaBot__sm = [FakeAdapter(valid=False)]
    update, context = make_update(text="https://example.com"), make_context()
    await bot.download_message_handler(update, context)
    update.effective_message.reply_text.assert_awaited_with("No media found", do_quote=True)


async def test_download_adapter_exception_is_logged(bot):
    bot._SocialMediaBot__sm = [FakeAdapter(error=RuntimeError("boom"))]
    update, context = make_update(text="https://example.com"), make_context()
    await bot.download_message_handler(update, context)
    # Falls through to "No media found" after swallowing+logging the error
    update.effective_message.reply_text.assert_awaited_with("No media found", do_quote=True)


async def test_adapters_run_in_a_worker_thread(bot):
    threads = []

    class ThreadRecordingAdapter(FakeAdapter):
        def get_media(self, url: str) -> Medias:
            threads.append(threading.current_thread().name)
            return super().get_media(url)

    bot._SocialMediaBot__sm = [ThreadRecordingAdapter()]
    update, context = make_update(text="x"), make_context()
    await bot.download_message_handler(update, context)
    # Downloads and re-encodes must not block the event loop, and run in the bot's own (large) pool
    assert len(threads) == 1 and threads[0].startswith("media")
    # A quick adapter gets no "downloading" notice
    assert texts(update) == ["No media found"]


async def test_slow_adapter_gets_a_status_message(bot, monkeypatch):
    monkeypatch.setattr("bot.social_media_bot.SLOW_DOWNLOAD_NOTICE", 0.01)

    class SlowAdapter(FakeAdapter):
        def get_media(self, url: str) -> Medias:
            time.sleep(0.2)
            return super().get_media(url)

    bot._SocialMediaBot__sm = [SlowAdapter(Medias(gifs=[Gif("http://g/1.gif")]))]
    update, context = make_update(text="x"), make_context()
    await bot.download_message_handler(update, context)
    assert texts(update) == ["Downloading, this might take a while…"]
    update.effective_message.reply_text.return_value.delete.assert_awaited_once()
    update.effective_message.reply_animation.assert_awaited_once()


async def test_slow_adapter_failure_still_removes_status_message(bot, monkeypatch):
    monkeypatch.setattr("bot.social_media_bot.SLOW_DOWNLOAD_NOTICE", 0.01)

    class SlowFailingAdapter(FakeAdapter):
        def get_media(self, url: str) -> Medias:
            time.sleep(0.2)
            raise RuntimeError("403")

    bot._SocialMediaBot__sm = [SlowFailingAdapter()]
    update, context = make_update(text="x"), make_context()
    await bot.download_message_handler(update, context)
    update.effective_message.reply_text.return_value.delete.assert_awaited_once()
    assert texts(update)[-1] == "No media found"


async def test_download_photos(bot):
    bot._SocialMediaBot__sm = [FakeAdapter(Medias(album=[Photo("http://p/1.jpg"), Photo("http://p/2.jpg")]))]
    update, context = make_update(text="x"), make_context()
    await bot.download_message_handler(update, context)
    update.effective_message.reply_media_group.assert_awaited_once()
    assert context.bot_data["stats"][1]["media_downloaded"] == 2


async def test_album_is_sent_in_groups_of_ten(bot):
    photos = [Photo(f"http://p/{i}.jpg") for i in range(12)]
    update, context = make_update(), make_context()
    context.bot_data["stats"] = {1: {"messages_handled": 0, "media_downloaded": 0}}
    await bot._reply_album(update, context, photos)
    sizes = [len(c.args[0]) for c in update.effective_message.reply_media_group.await_args_list]
    assert sizes == [10, 2]
    assert context.bot_data["stats"][1]["media_downloaded"] == 12


async def test_download_gifs(bot):
    bot._SocialMediaBot__sm = [FakeAdapter(Medias(gifs=[Gif("http://g/1.gif", 3, 320, 240)]))]
    update, context = make_update(text="x"), make_context()
    await bot.download_message_handler(update, context)
    update.effective_message.reply_animation.assert_awaited_once_with(
        animation="http://g/1.gif", duration=3, width=320, height=240, caption=None, do_quote=True
    )


async def test_download_video_url(bot, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: fake_response(1024))
    bot._SocialMediaBot__sm = [FakeAdapter(Medias(videos=[Video("http://v/s.mp4")]))]
    update, context = make_update(text="x"), make_context()
    await bot.download_message_handler(update, context)
    update.effective_message.reply_video.assert_awaited()


async def test_download_video_file(bot):
    f = MagicMock()
    bot._SocialMediaBot__sm = [FakeAdapter(Medias(videos=[Video(f, 60, 1280, 720)]))]
    update, context = make_update(text="x"), make_context()
    await bot.download_message_handler(update, context)
    update.effective_message.reply_video.assert_awaited_once_with(
        video=f, duration=60, width=1280, height=720, caption=None, do_quote=True, supports_streaming=True
    )
    f.close.assert_called_once()


async def test_download_audios(bot):
    f = MagicMock()
    bot._SocialMediaBot__sm = [FakeAdapter(Medias(audios=[Audio(f, "Song/Title", "Artist", 215)]))]
    update, context = make_update(text="x"), make_context()
    await bot.download_message_handler(update, context)
    update.effective_message.reply_audio.assert_awaited_once_with(
        audio=f,
        title="Song/Title",
        performer="Artist",
        duration=215,
        filename="Artist - Song_Title.m4a",
        caption=None,
        do_quote=True,
    )
    f.close.assert_called_once()
    assert context.bot_data["stats"][1]["media_downloaded"] == 1


async def test_reply_audios_error_sends_direct_link(bot):
    f = MagicMock()
    update, context = make_update(text="https://music.youtube.com/watch?v=abc"), make_context()
    context.bot_data["stats"] = {1: {"messages_handled": 0, "media_downloaded": 0}}
    update.effective_message.reply_audio.side_effect = telegram.error.BadRequest("too big")
    await bot._reply_audios(update, context, [Audio(f, "Title", "Artist", 1)])
    args = update.effective_message.reply_text.await_args.args[0]
    assert "https://music.youtube.com/watch?v=abc" in args
    f.close.assert_called_once()


async def test_mixed_album_keeps_order_and_metadata(bot):
    album = [Video("http://v/1.mp4", 12, 720, 1280), Photo("http://p/2.jpg"), Video("http://v/3.mp4")]
    bot._SocialMediaBot__sm = [FakeAdapter(Medias(album=album, caption="Carousel"))]
    update, context = make_update(text="x"), make_context()
    await bot.download_message_handler(update, context)

    group = update.effective_message.reply_media_group.await_args.args[0]
    assert [type(item).__name__ for item in group] == ["InputMediaVideo", "InputMediaPhoto", "InputMediaVideo"]
    assert [item.media for item in group] == ["http://v/1.mp4", "http://p/2.jpg", "http://v/3.mp4"]
    first = group[0].to_dict()
    assert (first["duration"], first["width"], first["height"], first["supports_streaming"]) == (12, 720, 1280, True)
    assert [item.caption for item in group] == ["Carousel", None, None]
    update.effective_message.reply_video.assert_not_awaited()
    assert context.bot_data["stats"][1]["media_downloaded"] == 3


async def test_rejected_mixed_album_falls_back_per_kind(bot, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: fake_response(1024))
    album = [Video("http://v/1.mp4"), Photo("http://p/2.jpg"), Photo("http://p/3.jpg")]
    update, context = make_update(), make_context()
    context.bot_data["stats"] = {1: {"messages_handled": 0, "media_downloaded": 0}}
    update.effective_message.reply_media_group.side_effect = [telegram.error.BadRequest("failed to get HTTP URL"), None]
    await bot._reply_album(update, context, album, "Text")

    # Retried as a photos-only group carrying the caption, then the video via the size-aware path
    retry = update.effective_message.reply_media_group.await_args_list[1].args[0]
    assert [item.media for item in retry] == ["http://p/2.jpg", "http://p/3.jpg"]
    assert retry[0].caption == "Text"
    update.effective_message.reply_video.assert_awaited_once_with(
        video="http://v/1.mp4", duration=None, width=None, height=None, caption=None, do_quote=True
    )
    assert context.bot_data["stats"][1]["media_downloaded"] == 3


async def test_rejected_videos_only_album_falls_back_with_caption(bot, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: fake_response(1024))
    update, context = make_update(), make_context()
    context.bot_data["stats"] = {1: {"messages_handled": 0, "media_downloaded": 0}}
    update.effective_message.reply_media_group.side_effect = telegram.error.BadRequest("failed to get HTTP URL")
    await bot._reply_album(update, context, [Video("http://v/1.mp4"), Video("http://v/2.mp4")], "Text")
    captions = [c.kwargs["caption"] for c in update.effective_message.reply_video.await_args_list]
    assert captions == ["Text", None]


async def test_rejected_photos_only_album_raises(bot):
    update, context = make_update(), make_context()
    context.bot_data["stats"] = {1: {"messages_handled": 0, "media_downloaded": 0}}
    update.effective_message.reply_media_group.side_effect = telegram.error.BadRequest("bad photo")
    with pytest.raises(telegram.error.BadRequest):
        await bot._reply_album(update, context, [Photo("http://p/1.jpg")])


# --- captions -----------------------------------------------------------------


async def test_caption_goes_on_first_sent_message_only(bot):
    f = MagicMock()
    media = Medias(
        album=[Photo(f"http://p/{i}.jpg") for i in range(11)],
        gifs=[Gif("http://g/1.gif")],
        videos=[Video(f)],
        caption="  Post text  ",
    )
    bot._SocialMediaBot__sm = [FakeAdapter(media)]
    update, context = make_update(text="x"), make_context()
    await bot.download_message_handler(update, context)

    groups = [c.args[0] for c in update.effective_message.reply_media_group.await_args_list]
    captions = [item.caption for group in groups for item in group]
    assert captions == ["Post text"] + [None] * 10
    assert update.effective_message.reply_animation.await_args.kwargs["caption"] is None
    assert update.effective_message.reply_video.await_args.kwargs["caption"] is None


async def test_caption_on_first_video_when_no_photos(bot):
    bot._SocialMediaBot__sm = [FakeAdapter(Medias(videos=[Video(MagicMock()), Video(MagicMock())], caption="Title"))]
    update, context = make_update(text="x"), make_context()
    await bot.download_message_handler(update, context)
    captions = [c.kwargs["caption"] for c in update.effective_message.reply_video.await_args_list]
    assert captions == ["Title", None]


async def test_caption_passed_to_audio(bot):
    audios = [Audio(MagicMock(), "T", "A", 1), Audio(MagicMock(), "T2", "A", 1)]
    bot._SocialMediaBot__sm = [FakeAdapter(Medias(audios=audios, caption="Text"))]
    update, context = make_update(text="x"), make_context()
    await bot.download_message_handler(update, context)
    captions = [c.kwargs["caption"] for c in update.effective_message.reply_audio.await_args_list]
    assert captions == ["Text", None]


async def test_captions_disabled(bot):
    bot._SocialMediaBot__captions = False
    bot._SocialMediaBot__sm = [FakeAdapter(Medias(gifs=[Gif("http://g/1.gif")], caption="Text"))]
    update, context = make_update(text="x"), make_context()
    await bot.download_message_handler(update, context)
    assert update.effective_message.reply_animation.await_args.kwargs["caption"] is None


async def test_blank_caption_is_dropped(bot):
    bot._SocialMediaBot__sm = [FakeAdapter(Medias(gifs=[Gif("http://g/1.gif")], caption=" \n "))]
    update, context = make_update(text="x"), make_context()
    await bot.download_message_handler(update, context)
    assert update.effective_message.reply_animation.await_args.kwargs["caption"] is None


@pytest.mark.parametrize(
    "text, expected_len",
    [
        ("a" * constants.MessageLimit.CAPTION_LENGTH, constants.MessageLimit.CAPTION_LENGTH),
        ("a" * 2000, constants.MessageLimit.CAPTION_LENGTH),
        # Emoji outside the BMP take two UTF-16 code units each
        ("😀" * 600, constants.MessageLimit.CAPTION_LENGTH - 1),
    ],
)
async def test_long_caption_is_truncated(bot, text, expected_len):
    bot._SocialMediaBot__sm = [FakeAdapter(Medias(gifs=[Gif("http://g/1.gif")], caption=text))]
    update, context = make_update(text="x"), make_context()
    await bot.download_message_handler(update, context)
    caption = update.effective_message.reply_animation.await_args.kwargs["caption"]
    assert len(caption.encode("utf-16-le")) // 2 == expected_len
    if len(text) > constants.MessageLimit.CAPTION_LENGTH:
        assert caption.endswith("…")


# --- _reply_videos size branches -------------------------------------------


async def test_reply_video_small_sends_by_url(bot, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: fake_response(1024))
    update, context = make_update(), make_context()
    context.bot_data["stats"] = {1: {"messages_handled": 0, "media_downloaded": 0}}
    await bot._reply_videos(update, context, [Video("http://v/small.mp4", 12, 720, 1280)])
    update.effective_message.reply_video.assert_awaited_with(
        video="http://v/small.mp4", duration=12, width=720, height=1280, caption=None, do_quote=True
    )


async def test_reply_video_medium_uploads_file(bot, monkeypatch):
    size = constants.FileSizeLimit.FILESIZE_DOWNLOAD + 10
    monkeypatch.setattr(requests, "get", lambda *a, **k: fake_response(size))
    update, context = make_update(), make_context()
    context.bot_data["stats"] = {1: {"messages_handled": 0, "media_downloaded": 0}}
    await bot._reply_videos(update, context, [Video("http://v/medium.mp4")])
    # Upload path posts a status message, uploads, then deletes the status message
    update.effective_message.reply_video.assert_awaited()
    update.effective_message.reply_text.return_value.delete.assert_awaited_once()


async def test_reply_video_error_sends_direct_link(bot, monkeypatch):
    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(requests, "get", boom)
    update, context = make_update(), make_context()
    context.bot_data["stats"] = {1: {"messages_handled": 0, "media_downloaded": 0}}
    await bot._reply_videos(update, context, [Video("http://v/err.mp4")])
    update.effective_message.reply_text.assert_awaited()


async def test_reply_video_file_error_sends_direct_link(bot):
    f = MagicMock()
    f.close = MagicMock()
    update, context = make_update(text="http://v/orig.mp4"), make_context()
    context.bot_data["stats"] = {1: {"messages_handled": 0, "media_downloaded": 0}}
    update.effective_message.reply_video.side_effect = requests.exceptions.ConnectionError("down")
    await bot._reply_videos(update, context, [Video(f)])
    update.effective_message.reply_text.assert_awaited()


# --- variants and compression ----------------------------------------------

UPLOAD = constants.FileSizeLimit.FILESIZE_UPLOAD
DOWNLOAD = constants.FileSizeLimit.FILESIZE_DOWNLOAD


def patch_sizes(monkeypatch, sizes: dict[str, int]) -> dict[str, MagicMock]:
    """Serve a fake response with the given Content-Length per URL; returns the responses by URL, in request order."""
    requested = {}

    def fake_get(url, *a, **k):
        requested[url] = fake_response(sizes[url])
        return requested[url]

    monkeypatch.setattr(requests, "get", fake_get)
    return requested


def patch_ffmpeg(monkeypatch, *, available=True, duration=None, transcoded=None) -> list[tuple]:
    """Stub media.ffmpeg; returns the list of transcode calls."""
    calls = []
    monkeypatch.setattr("media.ffmpeg.available", lambda: available)
    monkeypatch.setattr("media.ffmpeg.duration", lambda url: duration)

    def fake_transcode(inputs, duration, limit):
        calls.append((inputs, duration, limit))
        return transcoded

    monkeypatch.setattr("media.ffmpeg.transcode", fake_transcode)
    return calls


def texts(update) -> list[str]:
    return [c.args[0] for c in update.effective_message.reply_text.await_args_list]


def stats_context() -> MagicMock:
    context = make_context()
    context.bot_data["stats"] = {1: {"messages_handled": 0, "media_downloaded": 0}}
    return context


async def test_reply_video_uploads_first_variant_that_fits(bot, monkeypatch):
    sizes = {"http://v/1080.mp4": UPLOAD + 10, "http://v/720.mp4": DOWNLOAD + 10, "http://v/360.mp4": 1024}
    requested = patch_sizes(monkeypatch, sizes)
    calls = patch_ffmpeg(monkeypatch)
    update, context = make_update(), stats_context()
    video = Video("http://v/1080.mp4", 262, 1920, 1080, fallbacks=["http://v/720.mp4", "http://v/360.mp4"])
    await bot._reply_videos(update, context, [video])

    # 1080p is too big for an upload, 720p fits: 360p is never requested
    assert list(requested) == ["http://v/1080.mp4", "http://v/720.mp4"]
    requested["http://v/1080.mp4"].close.assert_called_once()
    sent = update.effective_message.reply_video.await_args.kwargs
    assert not isinstance(sent["video"], str)  # uploaded from a temp file
    assert (sent["duration"], sent["width"], sent["height"]) == (262, 1920, 1080)
    assert calls == []
    assert context.bot_data["stats"][1]["media_downloaded"] == 1


async def test_reply_video_small_variant_sent_by_url(bot, monkeypatch):
    patch_sizes(monkeypatch, {"http://v/1080.mp4": UPLOAD + 10, "http://v/360.mp4": 1024})
    update, context = make_update(), stats_context()
    await bot._reply_videos(update, context, [Video("http://v/1080.mp4", fallbacks=["http://v/360.mp4"])])
    update.effective_message.reply_video.assert_awaited_once_with(
        video="http://v/360.mp4", duration=None, width=None, height=None, caption=None, do_quote=True
    )


async def test_reply_video_compresses_smallest_variant_when_none_fits(bot, monkeypatch):
    patch_sizes(monkeypatch, {"http://v/1080.mp4": UPLOAD * 3, "http://v/720.mp4": UPLOAD + 10})
    out = io.BytesIO(b"compressed")
    calls = patch_ffmpeg(monkeypatch, transcoded=out)
    update, context = make_update(), stats_context()
    video = Video("http://v/1080.mp4", 262, 1920, 1080, fallbacks=["http://v/720.mp4"])
    await bot._reply_videos(update, context, [video], "Text")

    assert calls == [(["http://v/720.mp4"], 262, UPLOAD)]
    update.effective_message.reply_video.assert_awaited_once_with(
        video=out, duration=262, width=1920, height=1080, caption="Text", do_quote=True, supports_streaming=True
    )
    assert out.closed
    assert texts(update) == ["Video is too large, compressing it (this might take a while)"]
    update.effective_message.reply_text.return_value.delete.assert_awaited_once()
    assert context.bot_data["stats"][1]["media_downloaded"] == 1


async def test_reply_video_probes_unknown_duration(bot, monkeypatch):
    patch_sizes(monkeypatch, {"http://v/big.mp4": UPLOAD + 10})
    calls = patch_ffmpeg(monkeypatch, transcoded=io.BytesIO(b"x"))
    probed = []
    monkeypatch.setattr("media.ffmpeg.duration", lambda url: probed.append(url) or 100)
    update, context = make_update(), stats_context()
    await bot._reply_videos(update, context, [Video("http://v/big.mp4")])
    assert probed == ["http://v/big.mp4"]
    assert calls == [(["http://v/big.mp4"], 100, UPLOAD)]


@pytest.mark.parametrize(
    "video, ffmpeg_state",
    [
        (Video("http://v/huge.mp4", 3600), {}),  # too long for a decent re-encode
        (Video("http://v/huge.mp4"), {"duration": None}),  # duration unknown
        (Video("http://v/huge.mp4", 60), {"available": False}),  # no ffmpeg
    ],
)
async def test_reply_video_cant_compress_sends_link(bot, monkeypatch, video, ffmpeg_state):
    patch_sizes(monkeypatch, {"http://v/huge.mp4": UPLOAD + 10})
    calls = patch_ffmpeg(monkeypatch, **ffmpeg_state)
    update, context = make_update(), stats_context()
    await bot._reply_videos(update, context, [video])
    assert calls == []
    assert texts(update) == ["Video is too large for Telegram upload. Direct video link:\nhttp://v/huge.mp4"]


async def test_reply_video_compression_failure_links_best_variant(bot, monkeypatch):
    patch_sizes(monkeypatch, {"http://v/1080.mp4": UPLOAD * 3, "http://v/720.mp4": UPLOAD + 10})
    patch_ffmpeg(monkeypatch, transcoded=None)
    update, context = make_update(), stats_context()
    await bot._reply_videos(update, context, [Video("http://v/1080.mp4", 262, fallbacks=["http://v/720.mp4"])])
    update.effective_message.reply_text.return_value.delete.assert_awaited_once()
    assert texts(update)[-1] == "Video is too large for Telegram upload. Direct video link:\nhttp://v/1080.mp4"
    update.effective_message.reply_video.assert_not_awaited()


def broken_response(kind: str) -> MagicMock:
    response = fake_response(1024)
    if kind == "http":
        response.raise_for_status.side_effect = requests.HTTPError("403")
    else:
        response.headers = CaseInsensitiveDict()
    return response


@pytest.mark.parametrize("kind", ["http", "no-length"])
async def test_reply_video_unreachable_versions_are_skipped(bot, monkeypatch, kind):
    responses = {
        "http://v/1080.mp4": broken_response(kind),
        "http://v/720.mp4": broken_response(kind),
        "http://v/360.mp4": fake_response(1024),
    }
    monkeypatch.setattr(requests, "get", lambda url, *a, **k: responses[url])
    update, context = make_update(), stats_context()
    video = Video("http://v/1080.mp4", fallbacks=["http://v/720.mp4", "http://v/360.mp4"])
    await bot._reply_videos(update, context, [video])
    update.effective_message.reply_video.assert_awaited_once_with(
        video="http://v/360.mp4", duration=None, width=None, height=None, caption=None, do_quote=True
    )
    responses["http://v/1080.mp4"].close.assert_called_once()


async def test_reply_video_compresses_smallest_reachable_version(bot, monkeypatch):
    responses = {"http://v/1080.mp4": fake_response(UPLOAD * 3), "http://v/720.mp4": broken_response("http")}
    monkeypatch.setattr(requests, "get", lambda url, *a, **k: responses[url])
    calls = patch_ffmpeg(monkeypatch, transcoded=io.BytesIO(b"x"))
    update, context = make_update(), stats_context()
    await bot._reply_videos(update, context, [Video("http://v/1080.mp4", 262, fallbacks=["http://v/720.mp4"])])
    assert calls == [(["http://v/1080.mp4"], 262, UPLOAD)]


@pytest.mark.parametrize(
    "error", [requests.Timeout("read timed out"), requests.exceptions.ChunkedEncodingError("connection dropped")]
)
async def test_reply_video_network_errors_send_link(bot, monkeypatch, error):
    def fake_get(url, *a, **k):
        if isinstance(error, requests.Timeout):
            raise error
        response = fake_response(DOWNLOAD + 10)  # upload path: the download itself fails
        response.iter_content.side_effect = error
        return response

    monkeypatch.setattr(requests, "get", fake_get)
    update, context = make_update(), stats_context()
    await bot._reply_videos(update, context, [Video("http://v/1080.mp4")])
    assert texts(update)[-1] == "Error occurred when trying to send video. Direct link:\nhttp://v/1080.mp4"


async def test_video_downloads_run_in_media_threads(bot, monkeypatch):
    threads = []

    def fake_get(url, *a, **k):
        threads.append(threading.current_thread().name)
        response = fake_response(DOWNLOAD + 10)
        response.iter_content.side_effect = lambda **k: threads.append(threading.current_thread().name) or [b"x"]
        return response

    monkeypatch.setattr(requests, "get", fake_get)
    update, context = make_update(), stats_context()
    await bot._reply_videos(update, context, [Video("http://v/medium.mp4")])
    # Both the size probe and the 20-50 MB download stay off the event loop
    assert len(threads) == 2 and all(name.startswith("media") for name in threads)
    update.effective_message.reply_video.assert_awaited_once()


async def test_reply_video_compressed_upload_rejected_sends_link(bot, monkeypatch):
    patch_sizes(monkeypatch, {"http://v/big.mp4": UPLOAD + 10})
    out = io.BytesIO(b"x")
    patch_ffmpeg(monkeypatch, transcoded=out)
    update, context = make_update(), stats_context()
    update.effective_message.reply_video.side_effect = telegram.error.BadRequest("too big")
    await bot._reply_videos(update, context, [Video("http://v/big.mp4", 262)])
    assert out.closed
    update.effective_message.reply_text.return_value.delete.assert_awaited_once()
    assert texts(update)[-1] == "Error occurred when trying to send video. Direct link:\nhttp://v/big.mp4"


# --- base-class TelegramBot paths ------------------------------------------


def test_handlers_registered(bot):
    # start/help/stats/resetstats commands + download message + deny-access
    assert len(bot.application.handlers[0]) == 6


def test_updates_are_handled_concurrently(bot):
    # One user's long download must not hold up everyone else's messages
    assert bot.application.concurrent_updates > 1


async def test_post_init_sets_commands(bot, monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(type(bot.application.bot), "set_my_commands", mock)
    await bot._post_init(bot.application)
    mock.assert_awaited_once()


async def test_post_init_handles_badrequest(bot, monkeypatch):
    monkeypatch.setattr(
        type(bot.application.bot),
        "set_my_commands",
        AsyncMock(side_effect=telegram.error.BadRequest("nope")),
    )
    await bot._post_init(bot.application)  # must not raise


async def test_deny_access(bot):
    update, context = make_update(), make_context()
    await bot._deny_access(update, context)
    update.effective_message.reply_text.assert_awaited_once()


async def test_error_handler_forbidden_returns(bot):
    context = make_context()
    context.error = telegram.error.Forbidden("forbidden")
    await bot._error_handler(make_update(), context)
    context.bot.send_document.assert_not_awaited()


async def test_error_handler_conflict_returns(bot):
    context = make_context()
    context.error = telegram.error.Conflict("conflict")
    await bot._error_handler(make_update(), context)
    context.bot.send_document.assert_not_awaited()


async def test_error_handler_no_update_skips_report(bot):
    context = make_context()
    context.error = ValueError("boom")
    await bot._error_handler(None, context)
    context.bot.send_document.assert_not_awaited()


async def test_error_handler_reports(bot):
    context = make_context()
    context.error = ValueError("boom")
    update = make_update()
    await bot._error_handler(update, context)
    context.bot.send_document.assert_awaited_once()
    update.effective_message.reply_text.assert_awaited_once()


def test_run_polling(bot, monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(type(bot.application), "run_polling", mock)
    bot.run_polling()
    mock.assert_called_once()


def test_log_unknown_level(bot):
    # Unknown level names fall through getattr(logging, ...) -> AttributeError guard
    with pytest.raises(AttributeError):
        bot._log(make_update(), "not-a-level", "msg")


def test_media_uploads_get_a_long_write_timeout(bot):
    assert bot.application.bot.request._media_write_timeout == MEDIA_WRITE_TIMEOUT
