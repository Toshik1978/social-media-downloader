from unittest.mock import AsyncMock, MagicMock

import pytest
import requests
import telegram.error
from requests.structures import CaseInsensitiveDict
from telegram import constants

from media.media import Medias, SocialMedia
from tests.conftest import make_context, make_update


class FakeAdapter(SocialMedia):
    """Adapter returning a preset Medias (or raising) for the given url(s)."""

    def __init__(self, media: Medias | None = None, valid: bool = True, error: Exception | None = None):
        self._media = media if media is not None else Medias([], [], [], [])
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


async def test_download_photos(bot):
    bot._SocialMediaBot__sm = [FakeAdapter(Medias(["http://p/1.jpg", "http://p/2.jpg"], [], [], []))]
    update, context = make_update(text="x"), make_context()
    await bot.download_message_handler(update, context)
    update.effective_message.reply_media_group.assert_awaited_once()
    assert context.bot_data["stats"][1]["media_downloaded"] == 2


async def test_download_gifs(bot):
    bot._SocialMediaBot__sm = [FakeAdapter(Medias([], ["http://g/1.gif"], [], []))]
    update, context = make_update(text="x"), make_context()
    await bot.download_message_handler(update, context)
    update.effective_message.reply_animation.assert_awaited_once()


async def test_download_video_urls(bot, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: fake_response(1024))
    bot._SocialMediaBot__sm = [FakeAdapter(Medias([], [], ["http://v/s.mp4"], []))]
    update, context = make_update(text="x"), make_context()
    await bot.download_message_handler(update, context)
    update.effective_message.reply_video.assert_awaited()


async def test_download_video_files(bot):
    f = MagicMock()
    bot._SocialMediaBot__sm = [FakeAdapter(Medias([], [], [], [f]))]
    update, context = make_update(text="x"), make_context()
    await bot.download_message_handler(update, context)
    update.effective_message.reply_video.assert_awaited()
    f.close.assert_called_once()


# --- _reply_videos size branches -------------------------------------------


async def test_reply_video_small_sends_by_url(bot, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: fake_response(1024))
    update, context = make_update(), make_context()
    context.bot_data["stats"] = {1: {"messages_handled": 0, "media_downloaded": 0}}
    await bot._reply_videos(update, context, ["http://v/small.mp4"])
    update.effective_message.reply_video.assert_awaited_with(video="http://v/small.mp4", do_quote=True)


async def test_reply_video_medium_uploads_file(bot, monkeypatch):
    size = constants.FileSizeLimit.FILESIZE_DOWNLOAD + 10
    monkeypatch.setattr(requests, "get", lambda *a, **k: fake_response(size))
    update, context = make_update(), make_context()
    context.bot_data["stats"] = {1: {"messages_handled": 0, "media_downloaded": 0}}
    await bot._reply_videos(update, context, ["http://v/medium.mp4"])
    # Upload path posts a status message, uploads, then deletes the status message
    update.effective_message.reply_video.assert_awaited()
    update.effective_message.reply_text.return_value.delete.assert_awaited_once()


async def test_reply_video_too_large_sends_link(bot, monkeypatch):
    size = constants.FileSizeLimit.FILESIZE_UPLOAD + 10
    monkeypatch.setattr(requests, "get", lambda *a, **k: fake_response(size))
    update, context = make_update(), make_context()
    context.bot_data["stats"] = {1: {"messages_handled": 0, "media_downloaded": 0}}
    await bot._reply_videos(update, context, ["http://v/huge.mp4"])
    args = update.effective_message.reply_text.await_args.args[0]
    assert "http://v/huge.mp4" in args


async def test_reply_video_error_sends_direct_link(bot, monkeypatch):
    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(requests, "get", boom)
    update, context = make_update(), make_context()
    context.bot_data["stats"] = {1: {"messages_handled": 0, "media_downloaded": 0}}
    await bot._reply_videos(update, context, ["http://v/err.mp4"])
    update.effective_message.reply_text.assert_awaited()


async def test_reply_video_files_error_sends_direct_link(bot):
    f = MagicMock()
    f.close = MagicMock()
    update, context = make_update(text="http://v/orig.mp4"), make_context()
    context.bot_data["stats"] = {1: {"messages_handled": 0, "media_downloaded": 0}}
    update.effective_message.reply_video.side_effect = requests.exceptions.ConnectionError("down")
    await bot._reply_video_files(update, context, [f])
    update.effective_message.reply_text.assert_awaited()


# --- base-class TelegramBot paths ------------------------------------------


def test_handlers_registered(bot):
    # start/help/stats/resetstats commands + download message + deny-access
    assert len(bot.application.handlers[0]) == 6


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
