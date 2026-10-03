from media.media import Audio, Gif, Medias, Photo, SocialMedia, Video


def test_medias_stores_all_lists():
    album = [Photo("p1"), Video("v0")]
    gifs = [Gif("g1")]
    videos = [Video("v1")]
    audios = [Audio(None, "Title", "Artist", 10)]
    media = Medias(album, gifs, videos, audios)

    assert media.album is album
    assert media.gifs is gifs
    assert media.videos is videos
    assert media.audios is audios


def test_medias_empty():
    media = Medias()

    assert media.album == []
    assert media.gifs == []
    assert media.videos == []
    assert media.audios == []


def test_medias_defaults_are_not_shared():
    a, b = Medias(), Medias()
    a.album.append(Photo("p1"))
    assert b.album == []


def test_video_and_gif_metadata_is_optional():
    assert Video("v1") == Video("v1", None, None, None)
    assert Gif("g1") == Gif("g1", None, None, None)


def test_socialmedia_base_methods_are_noops():
    # The abstract base has no-op bodies; subclasses override them.
    base = SocialMedia()
    assert base.is_valid_url("x") is None
    assert base.get_media("x") is None


def test_video_fallbacks_default_empty_and_keyword():
    assert Video("http://v/1.mp4").fallbacks == []
    video = Video("http://v/1080.mp4", 10, 1920, 1080, fallbacks=["http://v/720.mp4"])
    assert video.fallbacks == ["http://v/720.mp4"]
    # Each instance gets its own list
    assert Video("a").fallbacks is not Video("b").fallbacks
