import logging
from unittest.mock import MagicMock

import pytest
import requests

from instagram.instagram import Instagram

logger = logging.getLogger("test")


@pytest.fixture
def instagram():
    return Instagram(logger, "test-key")


def _resp(payload):
    r = MagicMock()
    r.json.return_value = payload
    r.raise_for_status = MagicMock()
    return r


def test_graph_video_returns_video_url(instagram, monkeypatch):
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: _resp({"__typename": "GraphVideo", "video_url": "https://cdn/v.mp4"}),
    )
    media = instagram.get_media("https://instagram.com/reel/abc/")
    assert media.video_urls == ["https://cdn/v.mp4"]


def test_non_video_returns_empty(instagram, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _resp({"__typename": "GraphImage"}))
    media = instagram.get_media("https://instagram.com/p/abc/")
    assert media.photo_urls == [] and media.video_urls == []
