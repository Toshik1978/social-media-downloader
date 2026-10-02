import logging
from unittest.mock import MagicMock

import pytest
import requests

from media.media import Gif, Photo, Video
from twitter.twitter import Twitter

logger = logging.getLogger("test")


def resp(*, json=None, text="", url="", raises=None):
    r = MagicMock()
    r.url = url
    r.text = text
    if raises is not None:
        r.json.side_effect = raises
    else:
        r.json.return_value = json
    r.raise_for_status = MagicMock()
    return r


@pytest.fixture
def twitter():
    return Twitter(logger)


def test_get_media_no_tweet_id_returns_empty(twitter):
    media = twitter.get_media("https://twitter.com/user/photo/abc")
    assert media.album == [] and media.videos == [] and media.gifs == []


def test_get_media_full(twitter, monkeypatch):
    extended = [
        {"type": "image", "url": "https://pbs.twimg.com/media/a.jpg", "size": {"width": 800, "height": 600}},
        {
            "type": "gif",
            "url": "https://video.twimg.com/g.mp4",
            "duration_millis": 0,
            "size": {"width": 320, "height": 240},
        },
        {
            "type": "video",
            "url": "https://video.twimg.com/v.mp4",
            "duration_millis": 58932,
            "size": {"width": 720, "height": 1066},
        },
    ]
    monkeypatch.setattr(requests, "get", lambda *a, **k: resp(json={"media_extended": extended}))
    # orig-quality probe succeeds
    monkeypatch.setattr(requests, "head", lambda *a, **k: resp())

    media = twitter.get_media("https://twitter.com/user/status/123")
    assert media.caption is None
    assert len(media.album) == 1
    assert "format=jpg&name=orig" in media.album[0].url
    # A zero duration means "unknown" and is left to Telegram
    assert media.gifs == [Gif("https://video.twimg.com/g.mp4", None, 320, 240)]
    assert media.videos == [Video("https://video.twimg.com/v.mp4", 59, 720, 1066)]


@pytest.mark.parametrize(
    "text, caption",
    [
        ("Look at this https://t.co/abc123", "Look at this"),
        ("Two https://t.co/a1 https://t.co/b2\n", "Two"),
        ("Keep https://t.co/mid inside text", "Keep https://t.co/mid inside text"),
        ("https://t.co/only", None),
        ("", None),
    ],
)
def test_caption_strips_trailing_tco_links(twitter, monkeypatch, text, caption):
    monkeypatch.setattr(requests, "get", lambda *a, **k: resp(json={"text": text, "media_extended": []}))
    media = twitter.get_media("https://twitter.com/user/status/123")
    assert media.caption == caption


def test_get_media_without_metadata(twitter, monkeypatch):
    extended = [{"type": "video", "url": "https://video.twimg.com/v.mp4"}]
    monkeypatch.setattr(requests, "get", lambda *a, **k: resp(json={"media_extended": extended}))
    media = twitter.get_media("https://twitter.com/user/status/123")
    assert media.videos == [Video("https://video.twimg.com/v.mp4")]


def test_photo_orig_probe_falls_back_on_http_error(twitter, monkeypatch):
    extended = [{"type": "image", "url": "https://pbs.twimg.com/media/a.jpg"}]
    monkeypatch.setattr(requests, "get", lambda *a, **k: resp(json={"media_extended": extended}))

    def head_fail(*a, **k):
        r = resp()
        r.raise_for_status.side_effect = requests.HTTPError("404")
        return r

    monkeypatch.setattr(requests, "head", head_fail)
    media = twitter.get_media("https://x.com/user/status/123")
    assert media.album == [Photo("https://pbs.twimg.com/media/a.jpg")]


def test_tco_link_is_expanded(twitter, monkeypatch):
    def fake_get(url, *a, **k):
        if "t.co" in url:
            return resp(url="https://twitter.com/user/status/999")
        return resp(json={"media_extended": []})

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "head", lambda *a, **k: resp())
    media = twitter.get_media("https://t.co/abc123")
    assert media.album == []  # resolved + scraped, no media in payload


def test_scrape_media_html_error_raises(twitter, monkeypatch):
    html_text = '<meta content="User not found" property="og:description" />'
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: resp(text=html_text, raises=requests.exceptions.JSONDecodeError("e", "doc", 0)),
    )
    with pytest.raises(Exception, match="API returned error: User not found"):
        twitter.get_media("https://twitter.com/user/status/123")


def test_scrape_media_unparseable_reraises(twitter, monkeypatch):
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: resp(text="not html", raises=requests.exceptions.JSONDecodeError("e", "doc", 0)),
    )
    with pytest.raises(requests.exceptions.JSONDecodeError):
        twitter.get_media("https://twitter.com/user/status/123")
