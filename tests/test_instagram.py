import logging
from unittest.mock import MagicMock

import pytest
import requests

from instagram.instagram import Instagram
from media.media import Photo, ServiceUnavailable, Video

logger = logging.getLogger("test")


@pytest.fixture
def instagram():
    return Instagram(logger, "test-key")


def _resp(payload):
    r = MagicMock()
    r.json.return_value = payload
    r.raise_for_status = MagicMock()
    return r


def _patch(monkeypatch, payload):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _resp(payload))


def _error(status):
    r = MagicMock()
    r.raise_for_status.side_effect = requests.HTTPError(f"{status} Error", response=MagicMock(status_code=status))
    return r


def _patch_sequence(monkeypatch, outcomes):
    """requests.get answers with each outcome in turn (a response, or an exception to raise); returns the sleeps."""
    calls = iter(outcomes)

    def get(*a, **k):
        outcome = next(calls)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    sleeps = []
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr("instagram.instagram.sleep", sleeps.append)
    return sleeps


VIDEO_POST = {"status": True, "__typename": "GraphVideo", "video_url": "https://cdn/v.mp4"}


def test_graph_video_returns_video_with_metadata(instagram, monkeypatch):
    _patch(
        monkeypatch,
        {
            "status": True,
            "__typename": "GraphVideo",
            "is_video": True,
            "video_url": "https://cdn/v.mp4",
            "dimensions": {"height": 1920, "width": 1080},
            "video_duration": 16.739999771118164,
            "edge_media_to_caption": {"edges": [{"node": {"text": "DIY fish squishy"}}]},
        },
    )
    media = instagram.get_media("https://instagram.com/reel/abc/")
    assert media.videos == [Video("https://cdn/v.mp4", 17, 1080, 1920)]
    assert media.caption == "DIY fish squishy"
    assert media.album == []


def test_graph_video_without_metadata(instagram, monkeypatch):
    _patch(monkeypatch, {"status": True, "__typename": "GraphVideo", "video_url": "https://cdn/v.mp4"})
    media = instagram.get_media("https://instagram.com/reel/abc/")
    assert media.videos == [Video("https://cdn/v.mp4")]
    assert media.caption is None


def test_graph_image_returns_photo(instagram, monkeypatch):
    _patch(
        monkeypatch,
        {
            "status": True,
            "__typename": "GraphImage",
            "is_video": False,
            "display_url": "https://cdn/p.jpg",
            "dimensions": {"height": 1080, "width": 1080},
            "edge_media_to_caption": {"edges": []},
        },
    )
    media = instagram.get_media("https://instagram.com/p/abc/")
    assert media.album == [Photo("https://cdn/p.jpg")]
    assert media.caption is None
    assert media.videos == []


def test_graph_sidecar_keeps_order_in_album(instagram, monkeypatch):
    _patch(
        monkeypatch,
        {
            "status": True,
            "__typename": "GraphSidecar",
            "is_video": False,
            "display_url": "https://cdn/cover.jpg",
            "edge_media_to_caption": {"edges": [{"node": {"text": "Photo dump"}}]},
            "edge_sidecar_to_children": {
                "edges": [
                    {"node": {"__typename": "XDTGraphImage", "is_video": False, "display_url": "https://cdn/1.jpg"}},
                    {
                        "node": {
                            "__typename": "XDTGraphVideo",
                            "is_video": True,
                            "video_url": "https://cdn/2.mp4",
                            "display_url": "https://cdn/2.jpg",
                            "dimensions": {"height": 720, "width": 720},
                        }
                    },
                    {"node": {"__typename": "XDTGraphImage", "is_video": False, "display_url": "https://cdn/3.jpg"}},
                ]
            },
        },
    )
    media = instagram.get_media("https://instagram.com/p/abc/")
    # Order is kept; carousel videos carry no duration
    assert media.album == [
        Photo("https://cdn/1.jpg"),
        Video("https://cdn/2.mp4", None, 720, 720),
        Photo("https://cdn/3.jpg"),
    ]
    assert media.videos == []
    assert media.caption == "Photo dump"


def test_api_error_raises(instagram, monkeypatch):
    _patch(monkeypatch, {"status": False, "errorMessage": "This post does not exist."})
    with pytest.raises(Exception, match="API returned error: This post does not exist."):
        instagram.get_media("https://instagram.com/p/missing/")


def test_unsupported_type_returns_empty(instagram, monkeypatch):
    _patch(monkeypatch, {"status": True, "__typename": "GraphSomethingNew"})
    media = instagram.get_media("https://instagram.com/p/abc/")
    assert media.album == [] and media.videos == []


def test_server_error_is_retried(instagram, monkeypatch):
    sleeps = _patch_sequence(monkeypatch, [_error(500), requests.ConnectionError("reset"), _resp(VIDEO_POST)])
    media = instagram.get_media("https://instagram.com/reel/abc/")
    assert media.videos == [Video("https://cdn/v.mp4")]
    assert sleeps == [1, 3]


def test_persistent_server_error_raises_service_unavailable(instagram, monkeypatch):
    sleeps = _patch_sequence(monkeypatch, [_error(500), _error(502), _error(500)])
    with pytest.raises(ServiceUnavailable):
        instagram.get_media("https://instagram.com/reel/abc/")
    assert sleeps == [1, 3]


def test_client_error_is_not_retried(instagram, monkeypatch):
    sleeps = _patch_sequence(monkeypatch, [_error(429)])
    with pytest.raises(requests.HTTPError):
        instagram.get_media("https://instagram.com/reel/abc/")
    assert sleeps == []
