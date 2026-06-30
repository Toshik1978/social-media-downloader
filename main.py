import logging
import os

from dotenv import load_dotenv
from telegram import constants

from bot.social_media_bot import SocialMediaBot
from instagram.instagram import Instagram
from twitter.twitter import Twitter
from yt.youtube import YouTube


def main() -> None:
    """Console-script entry point."""

    load_dotenv()
    # Enable logging
    logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
    logger = logging.getLogger(__name__)
    # Create all clients
    sm = [
        Twitter(logger),
        Instagram(logger, os.getenv("RAPID_API_KEY") or ""),
        YouTube(logger, constants.FileSizeLimit.FILESIZE_UPLOAD),
    ]
    # Create a bot and run it
    user_ids = list(map(int, (os.getenv("USER_ID") or "").split(",")))
    bot = SocialMediaBot(logger, sm, os.getenv("BOT_TOKEN") or "", user_ids)
    bot.run_polling()


if __name__ == "__main__":
    main()
