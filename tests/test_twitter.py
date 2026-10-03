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


def ok(media=None, text=""):
    """An fxtwitter success payload."""
    tweet = {"text": text}
    if media is not None:
        tweet["media"] = {"all": media}
    return resp(json={"code": 200, "message": "OK", "tweet": tweet})


def mp4(name: str, bitrate: int) -> dict:
    return {"url": f"https://video.twimg.com/{name}.mp4", "bitrate": bitrate, "container": "mp4", "codec": "h264"}


@pytest.fixture
def twitter():
    return Twitter(logger)


def test_get_media_no_tweet_id_returns_empty(twitter):
    media = twitter.get_media("https://twitter.com/user/photo/abc")
    assert media.album == [] and media.videos == [] and media.gifs == []


def test_uses_fxtwitter(twitter, monkeypatch):
    calls = []
    monkeypatch.setattr(requests, "get", lambda url, **k: calls.append((url, k)) or ok())
    twitter.get_media("https://x.com/user/status/123")
    assert calls == [("https://api.fxtwitter.com/status/123", {"timeout": 30})]


def test_get_media_full(twitter, monkeypatch):
    media_all = [
        {"type": "photo", "url": "https://pbs.twimg.com/media/a.jpg", "width": 800, "height": 600},
        {"type": "gif", "url": "https://video.twimg.com/g.mp4", "duration": 0, "width": 320, "height": 240},
        {
            "type": "video",
            "url": "https://video.twimg.com/1080.mp4",
            "duration": 262.316,
            "width": 1920,
            "height": 1080,
            "formats": [
                {"url": "https://video.twimg.com/pl.m3u8", "container": "m3u8"},
                mp4("270", 256000),
                mp4("1080", 10368000),
                mp4("360", 832000),
                mp4("720", 2176000),
            ],
        },
    ]
    monkeypatch.setattr(requests, "get", lambda *a, **k: ok(media_all))
    # orig-quality probe succeeds
    monkeypatch.setattr(requests, "head", lambda *a, **k: resp())

    media = twitter.get_media("https://twitter.com/user/status/123")
    assert media.caption is None
    assert len(media.album) == 1
    assert "format=jpg&name=orig" in media.album[0].url
    # A zero duration means "unknown" and is left to Telegram
    assert media.gifs == [Gif("https://video.twimg.com/g.mp4", None, 320, 240)]
    # Best MP4 first, the rest by bitrate; the HLS playlist is skipped
    assert media.videos == [
        Video(
            "https://video.twimg.com/1080.mp4",
            262,
            1920,
            1080,
            fallbacks=[
                "https://video.twimg.com/720.mp4",
                "https://video.twimg.com/360.mp4",
                "https://video.twimg.com/270.mp4",
            ],
        )
    ]


def test_video_without_formats_uses_url(twitter, monkeypatch):
    media_all = [{"type": "video", "url": "https://video.twimg.com/v.mp4"}]
    monkeypatch.setattr(requests, "get", lambda *a, **k: ok(media_all))
    media = twitter.get_media("https://twitter.com/user/status/123")
    assert media.videos == [Video("https://video.twimg.com/v.mp4")]


def test_tweet_without_media(twitter, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: ok(text="Just text"))
    media = twitter.get_media("https://twitter.com/user/status/123")
    assert (media.album, media.gifs, media.videos, media.caption) == ([], [], [], "Just text")


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
    monkeypatch.setattr(requests, "get", lambda *a, **k: ok([], text))
    media = twitter.get_media("https://twitter.com/user/status/123")
    assert media.caption == caption


def test_photo_orig_probe_falls_back_on_http_error(twitter, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: ok([{"type": "photo", "url": "https://pbs.twimg.com/a.jpg"}]))

    def head_fail(*a, **k):
        r = resp()
        r.raise_for_status.side_effect = requests.HTTPError("404")
        return r

    monkeypatch.setattr(requests, "head", head_fail)
    media = twitter.get_media("https://x.com/user/status/123")
    assert media.album == [Photo("https://pbs.twimg.com/a.jpg")]


def test_tco_link_is_expanded(twitter, monkeypatch):
    def fake_get(url, *a, **k):
        if "t.co" in url:
            return resp(url="https://twitter.com/user/status/999")
        assert url == "https://api.fxtwitter.com/status/999"
        return ok([])

    monkeypatch.setattr(requests, "get", fake_get)
    media = twitter.get_media("https://t.co/abc123")
    assert media.album == []  # resolved + scraped, no media in payload


@pytest.mark.parametrize(
    "payload",
    [
        {"code": 404, "message": "NOT_FOUND", "tweet": None},
        {"code": 200, "message": "NOT_FOUND", "tweet": None},
    ],
)
def test_api_error_json_raises(twitter, monkeypatch, payload):
    monkeypatch.setattr(requests, "get", lambda *a, **k: resp(json=payload))
    with pytest.raises(Exception, match="API returned error: NOT_FOUND"):
        twitter.get_media("https://twitter.com/user/status/123")


def test_api_error_html_raises(twitter, monkeypatch):
    html_text = '<head><meta property="og:description" content="Sorry, that post doesn&#39;t exist :("/></head>'
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: resp(text=html_text, raises=requests.exceptions.JSONDecodeError("e", "doc", 0)),
    )
    with pytest.raises(Exception, match="API returned error: Sorry, that post doesn't exist"):
        twitter.get_media("https://twitter.com/user/status/123")


def test_api_unparseable_reraises(twitter, monkeypatch):
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: resp(text="not html", raises=requests.exceptions.JSONDecodeError("e", "doc", 0)),
    )
    with pytest.raises(requests.exceptions.JSONDecodeError):
        twitter.get_media("https://twitter.com/user/status/123")
