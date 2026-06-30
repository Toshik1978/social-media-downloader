import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

logger = logging.getLogger("test")


def make_update(text: str = "", user_id: int = 1) -> MagicMock:
    """Build a fake telegram Update with async reply methods."""
    update = MagicMock()
    update.effective_chat.id = 1000

    message = MagicMock()
    message.message_id = 99
    message.text = text
    message.reply_text = AsyncMock()
    message.reply_markdown_v2 = AsyncMock()
    message.reply_media_group = AsyncMock()
    message.reply_animation = AsyncMock()
    message.reply_video = AsyncMock()
    # reply_text returns a message-like object whose delete() is awaitable
    sent = MagicMock()
    sent.delete = AsyncMock()
    message.reply_text.return_value = sent
    update.effective_message = message

    update.effective_user.id = user_id
    update.effective_user.full_name = "Test User"
    update.effective_user.username = "tester"
    update.effective_user.mention_markdown_v2.return_value = "@tester"
    return update


def make_context() -> MagicMock:
    """Build a fake CallbackContext with a mutable bot_data and async bot."""
    context = MagicMock()
    context.bot_data = {}
    context.chat_data = {}
    context.user_data = {}
    context.error = None
    context.bot.send_document = AsyncMock()
    return context


@pytest.fixture
def bot(tmp_path, monkeypatch):
    """A real SocialMediaBot built offline (dummy token) in an isolated cwd.

    Constructing it exercises TelegramBot.__init__ and the dispatcher wiring
    without contacting Telegram. The persistence dir lands in tmp_path.
    """
    monkeypatch.chdir(tmp_path)
    from bot.social_media_bot import SocialMediaBot

    return SocialMediaBot(logger, [], "123456:AAHfaketoken", [1, 2])
