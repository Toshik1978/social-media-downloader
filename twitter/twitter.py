from logging import Logger
from typing import Optional
import re
import html
import requests
from urllib.parse import urlsplit, urlparse

from media.media import SocialMedia, Medias


class Twitter(SocialMedia):
    """Twitter is the class to manage Twitter medias."""

    __logger: Logger

    def __init__(self, logger: Logger):
        self.__logger = logger

    def is_valid_url(self, url: str) -> bool:
        """Check if URL points to valid social media data."""

        parsed_url = urlparse(url)
        return parsed_url.scheme in ['http', 'https'] and (
                parsed_url.netloc.endswith('t.co')
                or parsed_url.netloc.endswith('twitter.com')
                or parsed_url.netloc.endswith('x.com')
        )

    def get_media(self, url: str) -> Medias:
        """Get all available medias."""

        tweet_id = self.__extract_tweet_ids(url)
        if tweet_id is None:
            self.__logger.info('No supported tweet link found')
            return Medias([], [], [])

        tweet_media = self.__scrape_media(tweet_id)
        photos = [media for media in tweet_media if media["type"] == "image"]
        gifs = [media for media in tweet_media if media["type"] == "gif"]
        videos = [media for media in tweet_media if media["type"] == "video"]
        return Medias(self.__get_photos(photos), self.__get_gifs(gifs), self.__get_videos(videos), [])

    def __extract_tweet_ids(self, url: str) -> Optional[str]:
        # For t.co links
        match = re.search(r"t\.co\/[a-zA-Z0-9]+", url)
        if match is not None:
            link = match.group(0)
            l = requests.get('https://' + link).url
            self.__logger.info(f'Unshortened t.co link [https://{link} -> {l}]')
            url = l

        # Parse ID from received text
        match_id = re.search(r"(?:twitter|x)\.com/.{1,15}/(?:web|status(?:es)?)/([0-9]{1,20})", url)
        if match_id is not None:
            return match_id.group(1)
        return None

    def __scrape_media(self, tweet_id: str) -> list[dict]:
        self.__logger.info(f'Scraping tweet ID {tweet_id}')

        r = requests.get(f'https://api.vxtwitter.com/Twitter/status/{tweet_id}')
        r.raise_for_status()
        try:
            return r.json()['media_extended']
        except requests.exceptions.JSONDecodeError:  # the api likely returned an HTML page, try looking for an error message
            # <meta content="{message}" property="og:description" />
            if match := re.search(r'<meta content="(.*?)" property="og:description" />', r.text):
                raise Exception(f'API returned error: {html.unescape(match.group(1))}')
            raise

    def __get_photos(self, photos: list[dict]) -> list[str]:
        group = []
        for photo in photos:
            photo_url = photo['url']
            self.__logger.info(f'Photo[{len(group)}] url: {photo_url}')
            parsed_url = urlsplit(photo_url)

            # Try changing requested quality to 'orig'
            try:
                new_url = parsed_url._replace(query='format=jpg&name=orig').geturl()
                requests.head(new_url).raise_for_status()

                self.__logger.info('New photo url: ' + new_url)
                group.append(new_url)
            except requests.HTTPError:
                # Use original URL
                group.append(photo_url)
        return group

    def __get_gifs(self, gifs: list[dict]) -> list[str]:
        group = []
        for gif in gifs:
            gif_url = gif['url']
            self.__logger.info(f'Gif url: {gif_url}')
            group.append(gif_url)
        return group

    def __get_videos(self, videos: list[dict]) -> list[str]:
        group = []
        for video in videos:
            video_url = video['url']
            self.__logger.info(f'Video url: {video_url}')
            group.append(video_url)
        return group
