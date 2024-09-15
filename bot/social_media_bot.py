from logging import Logger
from tempfile import TemporaryFile
import requests
from telegram import Update, InputMediaPhoto, constants
from telegram.ext import CallbackContext
import telegram.error
from bot.telegram_bot import TelegramBot, command_description
from instagram.instagram import Instagram
from twitter.twitter import Twitter


class SocialMediaBot(TelegramBot):
    t: Twitter
    insta: Instagram

    def __init__(self, logger: Logger, t: Twitter, insta: Instagram, token: str, user_id: int):
        super().__init__(logger, token, user_id)
        self.t = t
        self.insta = insta

    @command_description("Start the bot")
    async def start_command_handler(self, update: Update, context: CallbackContext) -> None:
        """Send a message when the command /start is issued."""
        self._log(update, 'info', f'Received /start command from userId {update.effective_user.id}')
        user = update.effective_user
        await update.effective_message.reply_markdown_v2(
            fr'Hi {user.mention_markdown_v2()}\!' +
            '\nSend the link here and I will download media in the best available quality for you'
        )

    @command_description("Help message")
    async def help_command_handler(self, update: Update, context: CallbackContext) -> None:
        """Send a message when the command /help is issued."""
        self._log(update, 'info', f'Received /help command from userId {update.effective_user.id}')
        await update.effective_message.reply_text(
            'Send the link here and I will download media in the best available quality for you')

    @command_description("Get bot statistics")
    async def stats_command_handler(self, update: Update, context: CallbackContext) -> None:
        """Send stats when the command /stats is issued."""
        if not 'stats' in context.bot_data:
            context.bot_data['stats'] = {'messages_handled': 0, 'media_downloaded': 0}
            self._log(update, 'info', 'Initialized stats')
        self._log(update, 'info', f'Sent stats: {context.bot_data["stats"]}')
        await update.effective_message.reply_markdown_v2(
            f'*Bot stats:*\nMessages handled: *{context.bot_data["stats"].get("messages_handled")}*'
            f'\nMedia downloaded: *{context.bot_data["stats"].get("media_downloaded")}*')

    @command_description("Reset bot statistics")
    async def resetstats_command_handler(self, update: Update, context: CallbackContext) -> None:
        """Reset stats when the command /resetstats is issued."""
        stats = {'messages_handled': 0, 'media_downloaded': 0}
        context.bot_data['stats'] = stats
        self._log(update, 'info', 'Bot stats have been reset')
        await update.effective_message.reply_text("Bot stats have been reset")

    async def download_message_handler(self, update: Update, context: CallbackContext) -> None:
        """Handle the user message. Reply with found supported media."""
        self._log(update, 'info', 'Received message: ' + update.effective_message.text.replace("\n", ""))
        if not 'stats' in context.bot_data:
            context.bot_data['stats'] = {'messages_handled': 0, 'media_downloaded': 0}
            self.logger.info('Initialized stats')
        context.bot_data['stats']['messages_handled'] += 1

        url = update.effective_message.text
        # Get twitter media
        if Twitter.is_tweet(url):
            media = self.t.get_media(url)
            if len(media.photos) > 0:
                await self._reply_photos(update, context, media.photos)
            if len(media.gifs) > 0:
                await self._reply_gifs(update, context, media.gifs)
            if len(media.videos) > 0:
                await self._reply_videos(update, context, media.videos)
        elif Instagram.is_reel(url):
            media = self.insta.get_media(url)
            if media is not None:
                await self._reply_videos(update, context, [media])
        else:
            await update.effective_message.reply_text('No media found', quote=True)

    async def _reply_photos(self, update: Update, context: CallbackContext, photos: list[str]) -> None:
        group = []
        for url in photos:
            group.append(InputMediaPhoto(media=url))
        await update.effective_message.reply_media_group(group, quote=True)

        self._log(update, 'info', f'Sent photo group (len {len(group)})')
        context.bot_data['stats']['media_downloaded'] += len(group)

    async def _reply_gifs(self, update: Update, context: CallbackContext, gifs: list[str]) -> None:
        for url in gifs:
            await update.effective_message.reply_animation(animation=url, quote=True)

            self._log(update, 'info', 'Sent gif')
            context.bot_data['stats']['media_downloaded'] += 1

    async def _reply_videos(self, update: Update, context: CallbackContext, videos: list[str]) -> None:
        for url in videos:
            try:
                request = requests.get(url, stream=True)
                request.raise_for_status()
                if (video_size := int(request.headers['Content-Length'])) <= constants.FileSizeLimit.FILESIZE_DOWNLOAD:
                    # Try sending by url
                    await update.effective_message.reply_video(video=url, quote=True)
                    self._log(update, 'info', 'Sent video (download)')

                elif video_size <= constants.FileSizeLimit.FILESIZE_UPLOAD:
                    self._log(update, 'info', f'Video size ({video_size}) is bigger than '
                                              f'MAX_FILESIZE_UPLOAD, using upload method')
                    message = await update.effective_message.reply_text(
                        'Video is too large for direct download\nUsing upload method '
                        '(this might take a bit longer)',
                        quote=True)
                    with TemporaryFile() as tf:
                        self._log(update, 'info', f'Downloading video (Content-length: '
                                                  f'{request.headers["Content-length"]})')
                        for chunk in request.iter_content(chunk_size=128):
                            tf.write(chunk)
                        self._log(update, 'info', 'Video downloaded, uploading to Telegram')
                        tf.seek(0)
                        await update.effective_message.reply_video(video=tf, quote=True, supports_streaming=True)
                        self._log(update, 'info', 'Sent video (upload)')
                    await message.delete()

                else:
                    self._log(update, 'info', 'Video is too large, sending direct link')
                    await update.effective_message.reply_text(
                        f'Video is too large for Telegram upload. Direct video link:\n'
                        f'{url}', quote=True)
            except (
                    requests.HTTPError, KeyError, telegram.error.BadRequest, requests.exceptions.ConnectionError) as e:
                self._log(update, 'info', f'{e.__class__.__qualname__}: {e}')
                self._log(update, 'info', 'Error occurred when trying to send video, sending direct link')
                await update.effective_message.reply_text(f'Error occurred when trying to send video. Direct link:\n'
                                                          f'{url}', quote=True)

            context.bot_data['stats']['media_downloaded'] += 1
