import html
import re
from logging import Logger
from urllib.parse import urlparse, urlsplit

import requests

from media.media import Gif, Medias, Photo, SocialMedia, Video


class Twitter(SocialMedia):
    """Twitter is the class to manage Twitter medias."""

    __logger: Logger

    def __init__(self, logger: Logger):
        self.__logger = logger

    def is_valid_url(self, url: str) -> bool:
        """Check if URL points to valid social media data."""

        parsed_url = urlparse(url)
        return parsed_url.scheme in ["http", "https"] and (
            parsed_url.netloc.endswith("t.co")
            or parsed_url.netloc.endswith("twitter.com")
            or parsed_url.netloc.endswith("x.com")
        )

    def get_media(self, url: str) -> Medias:
        """Get all available medias."""

        tweet_id = self.__extract_tweet_ids(url)
        if tweet_id is None:
            self.__logger.info("No supported tweet link found")
            return Medias()

        tweet = self.__scrape_tweet(tweet_id)
        tweet_media = tweet["media_extended"]
        photos = [media for media in tweet_media if media["type"] == "image"]
        gifs = [media for media in tweet_media if media["type"] == "gif"]
        videos = [media for media in tweet_media if media["type"] == "video"]
        # Videos stay standalone: they can exceed the 20 MB Telegram fetches by URL, which fails a media group.
        return Medias(
            album=self.__get_photos(photos),
            gifs=self.__get_gifs(gifs),
            videos=self.__get_videos(videos),
            caption=self.__get_caption(tweet),
        )

    def __extract_tweet_ids(self, url: str) -> str | None:
        # For t.co links
        match = re.search(r"t\.co\/[a-zA-Z0-9]+", url)
        if match is not None:
            link = match.group(0)
            resolved = requests.get("https://" + link, timeout=30).url
            self.__logger.info(f"Unshortened t.co link [https://{link} -> {resolved}]")
            url = resolved

        # Parse ID from received text
        match_id = re.search(r"(?:twitter|x)\.com/.{1,15}/(?:web|status(?:es)?)/([0-9]{1,20})", url)
        if match_id is not None:
            return match_id.group(1)
        return None

    def __scrape_tweet(self, tweet_id: str) -> dict:
        self.__logger.info(f"Scraping tweet ID {tweet_id}")

        r = requests.get(f"https://api.vxtwitter.com/Twitter/status/{tweet_id}", timeout=30)
        r.raise_for_status()
        try:
            return r.json()
        except requests.exceptions.JSONDecodeError as exc:
            # The api likely returned an HTML page; try looking for an error message:
            # <meta content="{message}" property="og:description" />
            if match := re.search(r'<meta content="(.*?)" property="og:description" />', r.text):
                raise Exception(f"API returned error: {html.unescape(match.group(1))}") from exc
            raise

    def __get_caption(self, tweet: dict) -> str | None:
        # Tweets with media usually end with t.co links pointing back at the media itself.
        return re.sub(r"(\s*https://t\.co/\w+)+\s*$", "", tweet.get("text") or "") or None

    def __get_photos(self, photos: list[dict]) -> list[Photo]:
        group = []
        for photo in photos:
            photo_url = photo["url"]
            self.__logger.info(f"Photo[{len(group)}] url: {photo_url}")
            parsed_url = urlsplit(photo_url)

            # Try changing requested quality to 'orig'
            try:
                new_url = parsed_url._replace(query="format=jpg&name=orig").geturl()
                requests.head(new_url, timeout=30).raise_for_status()

                self.__logger.info("New photo url: " + new_url)
                group.append(Photo(new_url))
            except requests.HTTPError:
                # Use original URL
                group.append(Photo(photo_url))
        return group

    def __get_gifs(self, gifs: list[dict]) -> list[Gif]:
        group = []
        for gif in gifs:
            gif_url = gif["url"]
            self.__logger.info(f"Gif url: {gif_url}")
            group.append(Gif(gif_url, **self.__get_metadata(gif)))
        return group

    def __get_videos(self, videos: list[dict]) -> list[Video]:
        group = []
        for video in videos:
            video_url = video["url"]
            self.__logger.info(f"Video url: {video_url}")
            group.append(Video(video_url, **self.__get_metadata(video)))
        return group

    def __get_metadata(self, media: dict) -> dict:
        # The API reports 0 ms for media without a duration; missing values are left to Telegram.
        size = media.get("size") or {}
        duration = round((media.get("duration_millis") or 0) / 1000) or None
        return {"duration": duration, "width": size.get("width"), "height": size.get("height")}
