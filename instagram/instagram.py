from logging import Logger
from urllib.parse import urlparse

import requests

from media.media import Medias, SocialMedia


class Instagram(SocialMedia):
    """Instagram is the class to manage Instagram medias."""

    __logger: Logger
    __api_key: str

    def __init__(self, logger: Logger, api_key: str):
        self.__logger = logger
        self.__api_key = api_key

    def is_valid_url(self, url: str) -> bool:
        """Check if URL points to valid social media data."""

        parsed_url = urlparse(url)
        return parsed_url.scheme in ["http", "https"] and parsed_url.netloc.endswith("instagram.com")

    def get_media(self, url: str) -> Medias:
        """Get all available medias."""

        api_url = "https://instagram-looter2.p.rapidapi.com/post"
        querystring = {"url": url}
        headers = {"x-rapidapi-key": self.__api_key, "x-rapidapi-host": "instagram-looter2.p.rapidapi.com"}

        r = requests.get(api_url, headers=headers, params=querystring, timeout=30)
        r.raise_for_status()

        j = r.json()
        if j["__typename"] == "GraphVideo":
            return Medias([], [], [j["video_url"]], [])
        return Medias([], [], [], [])
