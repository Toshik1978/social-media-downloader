import logging
from unittest.mock import MagicMock

import pytest
import requests

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
    assert media.photo_urls == [] and media.video_urls == [] and media.gif_urls == []


def test_get_media_full(twitter, monkeypatch):
    extended = [
        {"type": "image", "url": "https://pbs.twimg.com/media/a.jpg"},
        {"type": "gif", "url": "https://video.twimg.com/g.mp4"},
        {"type": "video", "url": "https://video.twimg.com/v.mp4"},
    ]
    monkeypatch.setattr(requests, "get", lambda *a, **k: resp(json={"media_extended": extended}))
    # orig-quality probe succeeds
    monkeypatch.setattr(requests, "head", lambda *a, **k: resp())

    media = twitter.get_media("https://twitter.com/user/status/123")
    assert len(media.photo_urls) == 1
    assert "format=jpg&name=orig" in media.photo_urls[0]
    assert media.gif_urls == ["https://video.twimg.com/g.mp4"]
    assert media.video_urls == ["https://video.twimg.com/v.mp4"]


def test_photo_orig_probe_falls_back_on_http_error(twitter, monkeypatch):
    extended = [{"type": "image", "url": "https://pbs.twimg.com/media/a.jpg"}]
    monkeypatch.setattr(requests, "get", lambda *a, **k: resp(json={"media_extended": extended}))

    def head_fail(*a, **k):
        r = resp()
        r.raise_for_status.side_effect = requests.HTTPError("404")
        return r

    monkeypatch.setattr(requests, "head", head_fail)
    media = twitter.get_media("https://x.com/user/status/123")
    assert media.photo_urls == ["https://pbs.twimg.com/media/a.jpg"]


def test_tco_link_is_expanded(twitter, monkeypatch):
    def fake_get(url, *a, **k):
        if "t.co" in url:
            return resp(url="https://twitter.com/user/status/999")
        return resp(json={"media_extended": []})

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "head", lambda *a, **k: resp())
    media = twitter.get_media("https://t.co/abc123")
    assert media.photo_urls == []  # resolved + scraped, no media in payload


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
