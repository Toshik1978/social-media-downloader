from logging import Logger
from time import sleep
from urllib.parse import urlparse

import requests

from media.media import Medias, Photo, ServiceUnavailable, SocialMedia, Video

RETRY_DELAYS = (1, 3)
"""Seconds to wait before each retry of an API request that failed with a server error or a dropped connection."""


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

        # The API reports errors with HTTP 200 and "status": false.
        j = self.__get_post(url)
        if not j.get("status", True):
            raise Exception(f"API returned error: {j.get('errorMessage')}")

        typename = j.get("__typename")
        caption = self.__get_caption(j)
        if typename == "GraphVideo":
            return Medias(videos=[self.__get_video(j)], caption=caption)
        if typename == "GraphImage":
            return Medias(album=[self.__get_photo(j)], caption=caption)
        if typename == "GraphSidecar":
            # Carousel children are typed XDTGraphImage/XDTGraphVideo, so rely on is_video instead.
            # They keep their order as one album.
            nodes = [edge["node"] for edge in j["edge_sidecar_to_children"]["edges"]]
            album = [self.__get_video(node) if node["is_video"] else self.__get_photo(node) for node in nodes]
            return Medias(album=album, caption=caption)

        self.__logger.info(f"Unsupported post type: {typename}")
        return Medias()

    def __get_post(self, url: str) -> dict:
        api_url = "https://instagram-looter2.p.rapidapi.com/post"
        querystring = {"url": url}
        headers = {"x-rapidapi-key": self.__api_key, "x-rapidapi-host": "instagram-looter2.p.rapidapi.com"}

        # The API has outages answering HTTP 500 with an empty body; retry those, but not client errors (e.g. quota).
        for delay in (*RETRY_DELAYS, None):
            try:
                r = requests.get(api_url, headers=headers, params=querystring, timeout=30)
                r.raise_for_status()
                return r.json()
            except (requests.HTTPError, requests.ConnectionError) as e:
                if isinstance(e, requests.HTTPError) and e.response.status_code < 500:
                    raise
                if delay is None:
                    raise ServiceUnavailable(f"{e.__class__.__qualname__}: {e}") from e
                self.__logger.warning(f"Instagram API failed ({e.__class__.__qualname__}: {e}), retrying in {delay} s")
                sleep(delay)

    def __get_caption(self, post: dict) -> str | None:
        edges = (post.get("edge_media_to_caption") or {}).get("edges") or []
        return edges[0]["node"]["text"] if edges else None

    def __get_photo(self, node: dict) -> Photo:
        photo_url = node["display_url"]
        self.__logger.info(f"Photo url: {photo_url}")
        return Photo(photo_url)

    def __get_video(self, node: dict) -> Video:
        video_url = node["video_url"]
        self.__logger.info(f"Video url: {video_url}")
        # Carousel videos have no video_duration; posts report it in (float) seconds.
        dimensions = node.get("dimensions") or {}
        duration = round(node.get("video_duration") or 0) or None
        return Video(video_url, duration, dimensions.get("width"), dimensions.get("height"))
