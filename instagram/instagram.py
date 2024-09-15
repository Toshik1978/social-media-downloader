from logging import Logger
from typing import Optional
import re
import html
import requests
from urllib.parse import urlsplit


class Instagram:
    logger: Logger
    api_key: str

    @staticmethod
    def is_reel(url: str) -> bool:
        return re.search(r"instagram\.com\/reel\/[a-zA-Z0-9]+", url) is not None

    def __init__(self, logger: Logger, api_key: str):
        self.logger = logger
        self.api_key = api_key

    def get_media(self, url: str) -> Optional[str]:
        """Extract Instagram media URL from message."""
        api_url = "https://instagram-looter2.p.rapidapi.com/post"
        querystring = {"url": url}
        headers = {
            "x-rapidapi-key": self.api_key,
            "x-rapidapi-host": "instagram-looter2.p.rapidapi.com"
        }

        try:
            r = requests.get(api_url, headers=headers, params=querystring)
            r.raise_for_status()

            j = r.json()
            if j['__typename'] == 'GraphVideo':
                return j['video_url']
        except:
            self.logger.info(f'Can not get reel link [{url}]')
        return None
