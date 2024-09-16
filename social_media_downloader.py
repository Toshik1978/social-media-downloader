import logging
from telegram import constants

from config import BOT_TOKEN, USER_ID, RAPID_API_KEY
from bot.social_media_bot import SocialMediaBot
from twitter.twitter import Twitter
from instagram.instagram import Instagram
from yt.youtube import YouTube

if __name__ == '__main__':
    # Enable logging
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
    logger = logging.getLogger(__name__)
    # Create all clients
    sm = [Twitter(logger), Instagram(logger, RAPID_API_KEY), YouTube(logger, constants.FileSizeLimit.FILESIZE_UPLOAD)]
    # Create a bot and run it
    bot = SocialMediaBot(logger, sm, BOT_TOKEN, USER_ID)
    bot.run_polling()
