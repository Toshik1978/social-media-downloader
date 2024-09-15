from logging import Logger
from typing import Optional
import re
import html
import requests
from urllib.parse import urlsplit


"""Twitter API Exception."""
class TwitterAPIException(Exception):
    pass


"""TwitterMedia is the class to store results of a Tweet processing."""
class TwitterMedia:
    """Photos."""
    photos: list[str]
    """Gifs."""
    gifs: list[str]
    """Videos."""
    videos: list[str]

    def __init__(self, photos: list[str], gifs: list[str], videos: list[str]):
        self.photos = photos
        self.gifs = gifs
        self.videos = videos


"""Twitter is the class to manage Twitter medias."""
class Twitter:
    logger: Logger

    @staticmethod
    def is_tweet(url: str) -> bool:
        return re.search(r"t\.co\/[a-zA-Z0-9]+", url) is not None or \
            re.search(r"(?:twitter|x)\.com/.{1,15}/(?:web|status(?:es)?)/([0-9]{1,20})", url) is not None

    def __init__(self, logger: Logger):
        self.logger = logger

    def get_media(self, url: str) -> TwitterMedia:
        """Extract tweet media URL from message."""
        tweet_id = self.__extract_tweet_ids(url)
        if tweet_id is None:
            self.logger.info('No supported tweet link found')
            return TwitterMedia([], [], [])

        tweet_media = self.__scrape_media(tweet_id)
        photos = [media for media in tweet_media if media["type"] == "image"]
        gifs = [media for media in tweet_media if media["type"] == "gif"]
        videos = [media for media in tweet_media if media["type"] == "video"]
        return TwitterMedia(self.__get_photos(photos), self.__get_gifs(gifs), self.__get_videos(videos))

    def __extract_tweet_ids(self, url: str) -> Optional[str]:
        # For t.co links
        match = re.search(r"t\.co\/[a-zA-Z0-9]+", url)
        if match is not None:
            link = match.group(0)
            try:
                l = requests.get('https://' + link).url
                self.logger.info(f'Unshortened t.co link [https://{link} -> {l}]')
                url = l
            except:
                self.logger.info(f'Can not unshorten link [https://{link}]')

        # Parse ID from received text
        match_id = re.search(r"(?:twitter|x)\.com/.{1,15}/(?:web|status(?:es)?)/([0-9]{1,20})", url)
        if match_id is not None:
            return match_id.group(1)
        return None

    def __scrape_media(self, tweet_id: str) -> list[dict]:
        self.logger.info(f'Scraping tweet ID {tweet_id}')

        r = requests.get(f'https://api.vxtwitter.com/Twitter/status/{tweet_id}')
        r.raise_for_status()
        try:
            return r.json()['media_extended']
        except requests.exceptions.JSONDecodeError:  # the api likely returned an HTML page, try looking for an error message
            # <meta content="{message}" property="og:description" />
            if match := re.search(r'<meta content="(.*?)" property="og:description" />', r.text):
                raise TwitterAPIException(f'API returned error: {html.unescape(match.group(1))}')
            raise

    def __get_photos(self, photos: list[dict]) -> list[str]:
        group = []
        for photo in photos:
            photo_url = photo['url']
            self.logger.info(f'Photo[{len(group)}] url: {photo_url}')
            parsed_url = urlsplit(photo_url)

            # Try changing requested quality to 'orig'
            try:
                new_url = parsed_url._replace(query='format=jpg&name=orig').geturl()
                requests.head(new_url).raise_for_status()

                self.logger.info('New photo url: ' + new_url)
                group.append(new_url)
            except requests.HTTPError:
                group.append(photo_url)
        return group

    def __get_gifs(self, gifs: list[dict]) -> list[str]:
        group = []
        for gif in gifs:
            gif_url = gif['url']
            self.logger.info(f'Gif url: {gif_url}')
            group.append(gif_url)
        return group

    def __get_videos(self, videos: list[dict]) -> list[str]:
        group = []
        for video in videos:
            video_url = video['url']
            self.logger.info(f'Video url: {video_url}')
            group.append(video_url)
        return group
