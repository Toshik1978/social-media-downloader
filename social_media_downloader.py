import logging
from config import BOT_TOKEN, USER_ID, RAPID_API_KEY
from bot.social_media_bot import SocialMediaBot
from instagram.instagram import Instagram
from twitter.twitter import Twitter

if __name__ == '__main__':
    # Enable logging
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
    logger = logging.getLogger(__name__)
    # Create Twitter client
    t = Twitter(logger)
    # Create Instagram client
    insta = Instagram(logger, RAPID_API_KEY)
    # Create a bot and run it
    bot = SocialMediaBot(logger, t, insta, BOT_TOKEN, USER_ID)
    bot.run_polling()
