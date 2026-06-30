from logging import Logger
from tempfile import TemporaryFile

import requests
import telegram.error
from telegram import InputMediaPhoto, Update, constants
from telegram.ext import CallbackContext

from bot.telegram_bot import TelegramBot, command_description
from media.media import SocialMedia


class SocialMediaBot(TelegramBot):
    """Bot logic."""

    __sm: list[SocialMedia]

    def __init__(self, logger: Logger, sm: list[SocialMedia], token: str, user_ids: list[int]):
        super().__init__(logger, token, user_ids)
        self.__sm = sm

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

                if len(media.photo_urls) > 0:
                    await self._reply_photos(update, context, media.photo_urls)
                    is_found = True
                if len(media.gif_urls) > 0:
                    await self._reply_gifs(update, context, media.gif_urls)
                    is_found = True
                if len(media.video_urls) > 0:
                    await self._reply_videos(update, context, media.video_urls)
                    is_found = True
                if len(media.video_files) > 0:
                    await self._reply_video_files(update, context, media.video_files)
                    is_found = True

        if not is_found:
            await update.effective_message.reply_text("No media found", do_quote=True)

    async def _reply_photos(self, update: Update, context: CallbackContext, photos: list[str]) -> None:
        group = []
        for url in photos:
            group.append(InputMediaPhoto(media=url))
        await update.effective_message.reply_media_group(group, do_quote=True)

        self._log(update, "info", f"Sent photo group (len {len(group)})")
        context.bot_data["stats"][update.effective_user.id]["media_downloaded"] += len(group)

    async def _reply_gifs(self, update: Update, context: CallbackContext, gifs: list[str]) -> None:
        for url in gifs:
            await update.effective_message.reply_animation(animation=url, do_quote=True)

            self._log(update, "info", "Sent gif")
            context.bot_data["stats"][update.effective_user.id]["media_downloaded"] += 1

    async def _reply_videos(self, update: Update, context: CallbackContext, videos: list[str]) -> None:
        for url in videos:
            try:
                request = requests.get(url, stream=True, timeout=30)
                request.raise_for_status()
                if (video_size := int(request.headers["Content-Length"])) <= constants.FileSizeLimit.FILESIZE_DOWNLOAD:
                    # Try sending by url
                    await update.effective_message.reply_video(video=url, do_quote=True)
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
                        for chunk in request.iter_content(chunk_size=262144):
                            tf.write(chunk)
                        self._log(update, "info", "Video downloaded, uploading to Telegram")
                        tf.seek(0)
                        await update.effective_message.reply_video(video=tf, do_quote=True, supports_streaming=True)
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

            context.bot_data["stats"][update.effective_user.id]["media_downloaded"] += 1

    async def _reply_video_files(self, update: Update, context: CallbackContext, videos: list[TemporaryFile]) -> None:
        for f in videos:
            try:
                message = await update.effective_message.reply_text(
                    "Video is too large for direct download\nUsing upload method (this might take a bit longer)",
                    do_quote=True,
                )

                await update.effective_message.reply_video(video=f, do_quote=True, supports_streaming=True)
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

            context.bot_data["stats"][update.effective_user.id]["media_downloaded"] += 1
