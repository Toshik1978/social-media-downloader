from collections.abc import Sequence
from itertools import batched
from logging import Logger
from tempfile import TemporaryFile
from typing import IO

import requests
import telegram.error
from telegram import InputMediaPhoto, InputMediaVideo, Update, constants
from telegram.ext import CallbackContext

from bot.telegram_bot import TelegramBot, command_description
from media.media import Audio, Gif, Medias, Photo, SocialMedia, Video

DOWNLOAD_CHUNK_SIZE = 256 * 1024
"""Read buffer for streaming a video to a temp file: big enough to keep per-chunk overhead low, small
enough to keep memory flat."""


class SocialMediaBot(TelegramBot):
    """Bot logic."""

    __sm: list[SocialMedia]
    __captions: bool

    def __init__(self, logger: Logger, sm: list[SocialMedia], token: str, user_ids: list[int], captions: bool = True):
        super().__init__(logger, token, user_ids)
        self.__sm = sm
        self.__captions = captions

    @command_description("Start the bot")
    async def start_command_handler(self, update: Update, context: CallbackContext) -> None:
        """Send a message when the command /start is issued."""

        self._log(update, "info", f"Received /start command from userId {update.effective_user.id}")
        user = update.effective_user
        await update.effective_message.reply_markdown_v2(
            rf"Hi {user.mention_markdown_v2()}\!"
            + "\nSend the link here and I will download media in the best available quality for you"
        )

    @command_description("Help message")
    async def help_command_handler(self, update: Update, context: CallbackContext) -> None:
        """Send a message when the command /help is issued."""

        self._log(update, "info", f"Received /help command from userId {update.effective_user.id}")
        await update.effective_message.reply_text(
            "Send the link here and I will download media in the best available quality for you"
        )

    @command_description("Get bot statistics")
    async def stats_command_handler(self, update: Update, context: CallbackContext) -> None:
        """Send stats when the command /stats is issued."""

        self.__initialize_stats(update, context)
        stats = context.bot_data["stats"][update.effective_user.id]
        self._log(update, "info", f"Sent stats: {stats}")
        await update.effective_message.reply_markdown_v2(
            f"*Bot stats:*\nMessages handled: *{stats.get('messages_handled')}*"
            f"\nMedia downloaded: *{stats.get('media_downloaded')}*"
        )

    def __initialize_stats(self, update: Update, context: CallbackContext) -> None:
        if "stats" not in context.bot_data:
            context.bot_data["stats"] = {}
        if update.effective_user.id not in context.bot_data["stats"]:
            context.bot_data["stats"][update.effective_user.id] = {"messages_handled": 0, "media_downloaded": 0}
            self._log(update, "info", f"Initialized stats: {update.effective_user.id}")

    @command_description("Reset bot statistics")
    async def resetstats_command_handler(self, update: Update, context: CallbackContext) -> None:
        """Reset stats when the command /resetstats is issued."""

        self.__initialize_stats(update, context)
        context.bot_data["stats"][update.effective_user.id] = {"messages_handled": 0, "media_downloaded": 0}
        self._log(update, "info", "Bot stats have been reset")
        await update.effective_message.reply_text("Bot stats have been reset")

    async def download_message_handler(self, update: Update, context: CallbackContext) -> None:
        """Handle the user message. Reply with found supported media."""

        self._log(update, "info", "Received message: " + update.effective_message.text.replace("\n", ""))
        self.__initialize_stats(update, context)
        context.bot_data["stats"][update.effective_user.id]["messages_handled"] += 1

        url = update.effective_message.text
        # Find the relevant social media adapter
        is_found = False
        for social in self.__sm:
            if social.is_valid_url(url):
                try:
                    media = social.get_media(url)
                except Exception as e:
                    self._log(
                        update,
                        "warning",
                        f"{social.__class__.__name__} failed to get media: {e.__class__.__qualname__}: {e}",
                    )
                    continue

                # The caption describes the whole post, so only the first sent message carries it.
                caption = self.__get_caption(media)
                if len(media.album) > 0:
                    await self._reply_album(update, context, media.album, caption)
                    is_found, caption = True, None
                if len(media.gifs) > 0:
                    await self._reply_gifs(update, context, media.gifs, caption)
                    is_found, caption = True, None
                if len(media.videos) > 0:
                    await self._reply_videos(update, context, media.videos, caption)
                    is_found, caption = True, None
                if len(media.audios) > 0:
                    await self._reply_audios(update, context, media.audios, caption)
                    is_found = True

        if not is_found:
            await update.effective_message.reply_text("No media found", do_quote=True)

    def __get_caption(self, media: Medias) -> str | None:
        if not self.__captions or not media.caption or not (caption := media.caption.strip()):
            return None

        # Telegram counts the caption length in UTF-16 code units.
        limit = constants.MessageLimit.CAPTION_LENGTH
        if len(caption.encode("utf-16-le")) // 2 <= limit:
            return caption
        truncated, length = [], 0
        for char in caption:
            length += len(char.encode("utf-16-le")) // 2
            if length > limit - 1:
                break
            truncated.append(char)
        return "".join(truncated).rstrip() + "…"

    async def _reply_album(
        self, update: Update, context: CallbackContext, album: list[Photo | Video], caption: str | None = None
    ) -> None:
        # Telegram limits a media group to 10 items.
        for batch in batched(album, constants.MediaGroupLimit.MAX_MEDIA_LENGTH, strict=False):
            try:
                await self.__reply_media_group(update, context, batch, caption)
            except telegram.error.BadRequest as e:
                # Most likely a video Telegram can't fetch by URL (over 20 MB). Send the batch per media kind,
                # so videos go through the size-aware path; this loses the order within the batch.
                videos = [item for item in batch if isinstance(item, Video)]
                if not videos:
                    raise
                self._log(update, "info", f"{e.__class__.__qualname__}: {e}")
                self._log(update, "info", "Media group was rejected, sending photos and videos separately")
                photos = [item for item in batch if isinstance(item, Photo)]
                if photos:
                    await self.__reply_media_group(update, context, photos, caption)
                    caption = None
                await self._reply_videos(update, context, videos, caption)
            caption = None

    async def __reply_media_group(
        self, update: Update, context: CallbackContext, items: Sequence[Photo | Video], caption: str | None
    ) -> None:
        # A caption on the first item is shown as the caption of the whole group.
        group = []
        for i, item in enumerate(items):
            item_caption = None if i else caption
            if isinstance(item, Photo):
                group.append(InputMediaPhoto(media=item.url, caption=item_caption))
            else:
                group.append(
                    InputMediaVideo(
                        media=item.source,
                        duration=item.duration,
                        width=item.width,
                        height=item.height,
                        caption=item_caption,
                        supports_streaming=True,
                    )
                )
        await update.effective_message.reply_media_group(group, do_quote=True)

        self._log(update, "info", f"Sent media group (len {len(group)})")
        context.bot_data["stats"][update.effective_user.id]["media_downloaded"] += len(group)

    async def _reply_gifs(
        self, update: Update, context: CallbackContext, gifs: list[Gif], caption: str | None = None
    ) -> None:
        for gif in gifs:
            await update.effective_message.reply_animation(
                animation=gif.url,
                duration=gif.duration,
                width=gif.width,
                height=gif.height,
                caption=caption,
                do_quote=True,
            )
            caption = None

            self._log(update, "info", "Sent gif")
            context.bot_data["stats"][update.effective_user.id]["media_downloaded"] += 1

    async def _reply_videos(
        self, update: Update, context: CallbackContext, videos: list[Video], caption: str | None = None
    ) -> None:
        for video in videos:
            if isinstance(video.source, str):
                await self.__reply_video_url(update, video, video.source, caption)
            else:
                await self.__reply_video_file(update, video, video.source, caption)
            caption = None

            context.bot_data["stats"][update.effective_user.id]["media_downloaded"] += 1

    async def __reply_video_url(self, update: Update, video: Video, url: str, caption: str | None) -> None:
        try:
            request = requests.get(url, stream=True, timeout=30)
            request.raise_for_status()
            if (video_size := int(request.headers["Content-Length"])) <= constants.FileSizeLimit.FILESIZE_DOWNLOAD:
                # Try sending by url
                await update.effective_message.reply_video(
                    video=url,
                    duration=video.duration,
                    width=video.width,
                    height=video.height,
                    caption=caption,
                    do_quote=True,
                )
                self._log(update, "info", "Sent video (download)")

            elif video_size <= constants.FileSizeLimit.FILESIZE_UPLOAD:
                self._log(
                    update,
                    "info",
                    f"Video size ({video_size}) is bigger than MAX_FILESIZE_UPLOAD, using upload method",
                )
                message = await update.effective_message.reply_text(
                    "Video is too large for direct download\nUsing upload method (this might take a bit longer)",
                    do_quote=True,
                )
                with TemporaryFile() as tf:
                    self._log(
                        update, "info", f"Downloading video (Content-length: {request.headers['Content-length']})"
                    )
                    for chunk in request.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                        tf.write(chunk)
                    self._log(update, "info", "Video downloaded, uploading to Telegram")
                    tf.seek(0)
                    await update.effective_message.reply_video(
                        video=tf,
                        duration=video.duration,
                        width=video.width,
                        height=video.height,
                        caption=caption,
                        do_quote=True,
                        supports_streaming=True,
                    )
                    self._log(update, "info", "Sent video (upload)")
                await message.delete()

            else:
                self._log(update, "info", "Video is too large, sending direct link")
                await update.effective_message.reply_text(
                    f"Video is too large for Telegram upload. Direct video link:\n{url}", do_quote=True
                )
        except (requests.HTTPError, KeyError, telegram.error.BadRequest, requests.exceptions.ConnectionError) as e:
            self._log(update, "info", f"{e.__class__.__qualname__}: {e}")
            self._log(update, "info", "Error occurred when trying to send video, sending direct link")
            await update.effective_message.reply_text(
                f"Error occurred when trying to send video. Direct link:\n{url}", do_quote=True
            )

    async def __reply_video_file(self, update: Update, video: Video, f: IO[bytes], caption: str | None) -> None:
        try:
            message = await update.effective_message.reply_text(
                "Video is too large for direct download\nUsing upload method (this might take a bit longer)",
                do_quote=True,
            )

            await update.effective_message.reply_video(
                video=f,
                duration=video.duration,
                width=video.width,
                height=video.height,
                caption=caption,
                do_quote=True,
                supports_streaming=True,
            )
            f.close()
            self._log(update, "info", "Sent video (upload)")
            await message.delete()
        except (requests.HTTPError, KeyError, telegram.error.BadRequest, requests.exceptions.ConnectionError) as e:
            self._log(update, "info", f"{e.__class__.__qualname__}: {e}")
            self._log(update, "info", "Error occurred when trying to send video, sending direct link")
            await update.effective_message.reply_text(
                f"Error occurred when trying to send video. Direct link:\n{update.effective_message.text}",
                do_quote=True,
            )

    async def _reply_audios(
        self, update: Update, context: CallbackContext, audios: list[Audio], caption: str | None = None
    ) -> None:
        for audio in audios:
            try:
                await update.effective_message.reply_audio(
                    audio=audio.file,
                    title=audio.title,
                    performer=audio.performer,
                    duration=audio.duration,
                    filename=f"{audio.performer} - {audio.title}.m4a".replace("/", "_"),
                    caption=caption,
                    do_quote=True,
                )
                self._log(update, "info", "Sent audio (upload)")
            except telegram.error.BadRequest as e:
                self._log(update, "info", f"{e.__class__.__qualname__}: {e}")
                self._log(update, "info", "Error occurred when trying to send audio, sending direct link")
                await update.effective_message.reply_text(
                    f"Error occurred when trying to send audio. Direct link:\n{update.effective_message.text}",
                    do_quote=True,
                )
            finally:
                audio.file.close()
            caption = None

            context.bot_data["stats"][update.effective_user.id]["media_downloaded"] += 1
