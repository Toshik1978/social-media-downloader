from media.media import Medias, SocialMedia


def test_medias_stores_all_four_lists():
    photos = ["p1"]
    gifs = ["g1"]
    videos = ["v1"]
    files = []
    media = Medias(photos, gifs, videos, files)

    assert media.photo_urls is photos
    assert media.gif_urls is gifs
    assert media.video_urls is videos
    assert media.video_files is files


def test_medias_empty():
    media = Medias([], [], [], [])

    assert media.photo_urls == []
    assert media.gif_urls == []
    assert media.video_urls == []
    assert media.video_files == []


def test_socialmedia_base_methods_are_noops():
    # The abstract base has no-op bodies; subclasses override them.
    base = SocialMedia()
    assert base.is_valid_url("x") is None
    assert base.get_media("x") is None
