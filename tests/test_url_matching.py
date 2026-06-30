import logging

import pytest

from instagram.instagram import Instagram
from twitter.twitter import Twitter
from yt.youtube import YouTube

logger = logging.getLogger("test")


@pytest.fixture
def twitter():
    return Twitter(logger)


@pytest.fixture
def instagram():
    return Instagram(logger, "test-key")


@pytest.fixture
def youtube():
    return YouTube(logger, 1024)


@pytest.mark.parametrize(
    "url",
    [
        "https://twitter.com/user/status/123",
        "https://x.com/user/status/123",
        "https://t.co/abc123",
        "http://twitter.com/user/status/123",
        "https://mobile.twitter.com/user/status/123",
    ],
)
def test_twitter_accepts_known_hosts(twitter, url):
    assert twitter.is_valid_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://instagram.com/p/abc/",
        "https://youtube.com/watch?v=abc",
        "ftp://twitter.com/user/status/123",
        "not a url",
        "https://twitterclone.evil.com/status/1",
    ],
)
def test_twitter_rejects_others(twitter, url):
    assert twitter.is_valid_url(url) is False


@pytest.mark.parametrize(
    "url",
    [
        "https://instagram.com/p/abc/",
        "https://www.instagram.com/reel/abc/",
        "http://instagram.com/p/abc/",
    ],
)
def test_instagram_accepts_known_hosts(instagram, url):
    assert instagram.is_valid_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://twitter.com/user/status/123",
        "https://youtu.be/abc",
        "ftp://instagram.com/p/abc/",
    ],
)
def test_instagram_rejects_others(instagram, url):
    assert instagram.is_valid_url(url) is False


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com/watch?v=abc",
        "https://www.youtube.com/watch?v=abc",
        "https://youtu.be/abc",
        "http://youtu.be/abc",
    ],
)
def test_youtube_accepts_known_hosts(youtube, url):
    assert youtube.is_valid_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://twitter.com/user/status/123",
        "https://instagram.com/p/abc/",
        "ftp://youtube.com/watch?v=abc",
        "https://youtube.evil.com/watch?v=abc",
    ],
)
def test_youtube_rejects_others(youtube, url):
    assert youtube.is_valid_url(url) is False
