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
        tweet_media = (tweet.get("media") or {}).get("all") or []
        photos = [media for media in tweet_media if media["type"] == "photo"]
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

        # Errors come back as JSON too (e.g. HTTP 404 {"code": 404, "message": "NOT_FOUND"}), so no raise_for_status.
        r = requests.get(f"https://api.fxtwitter.com/status/{tweet_id}", timeout=30)
        try:
            j = r.json()
        except requests.exceptions.JSONDecodeError as exc:
            # The api likely returned an HTML page; try looking for an error message:
            # <meta property="og:description" content="{message}"/>
            if match := re.search(r'<meta property="og:description" content="(.*?)"', r.text):
                raise Exception(f"API returned error: {html.unescape(match.group(1))}") from exc
            raise
        if j.get("code") != 200 or not j.get("tweet"):
            raise Exception(f"API returned error: {j.get('message')}")
        return j["tweet"]

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
            # Every MP4 rendition, best first, so the bot can fall back to a smaller one; HLS playlists are skipped.
            formats = [f for f in video.get("formats") or [] if f.get("container") == "mp4"]
            urls = [f["url"] for f in sorted(formats, key=lambda f: f.get("bitrate") or 0, reverse=True)]
            urls = urls or [video["url"]]
            self.__logger.info(f"Video urls: {urls}")
            group.append(Video(urls[0], **self.__get_metadata(video), fallbacks=urls[1:]))
        return group

    def __get_metadata(self, media: dict) -> dict:
        # The API reports 0 s for media without a duration; missing values are left to Telegram.
        duration = round(media.get("duration") or 0) or None
        return {"duration": duration, "width": media.get("width"), "height": media.get("height")}
