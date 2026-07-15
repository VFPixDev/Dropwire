import asyncio

from src.providers.oembed import OEmbedData
from src.providers.soundcloud import fetch_soundcloud_card
from src.providers.spotify import extract_spotify_entity, fetch_spotify_card


def test_spotify_card_works_without_web_api_credentials(monkeypatch):
    async def fake_oembed(endpoint, shared_url, expected_provider):
        return OEmbedData(
            title="Example Track",
            thumbnail_url="https://i.scdn.co/image/cover",
            author_name=None,
            author_url=None,
            html='<iframe src="https://open.spotify.com/embed/track/11dFghVXANMlKmJXsNCbNl"></iframe>',
        )

    monkeypatch.setattr("src.providers.spotify.fetch_oembed", fake_oembed)
    monkeypatch.setattr("src.providers.spotify.config.SPOTIFY_CLIENT_ID", "")
    monkeypatch.setattr("src.providers.spotify.config.SPOTIFY_CLIENT_SECRET", "")
    card = asyncio.run(fetch_spotify_card("https://open.spotify.com/track/11dFghVXANMlKmJXsNCbNl"))

    assert card.title == "Example Track"
    assert card.source == "spotify"
    assert card.media_type == "music"
    assert card.thumbnail_url == "https://i.scdn.co/image/cover"
    assert card.hashtags == ["#spotify", "#music"]


def test_spotify_short_link_entity_can_be_read_from_embed_html():
    oembed = OEmbedData(
        title="Track",
        thumbnail_url=None,
        author_name=None,
        author_url=None,
        html='<iframe src="https://open.spotify.com/embed/episode/7makk4oTQel546B0PZlDM5"></iframe>',
    )
    assert extract_spotify_entity("https://spotify.link/example", oembed) == (
        "episode",
        "7makk4oTQel546B0PZlDM5",
    )


def test_soundcloud_card_uses_author_and_clean_title(monkeypatch):
    async def fake_oembed(endpoint, shared_url, expected_provider):
        return OEmbedData(
            title="Flickermood by Forss",
            thumbnail_url="https://i1.sndcdn.com/artwork.jpg",
            author_name="Forss",
            author_url="https://soundcloud.com/forss",
            html=None,
        )

    monkeypatch.setattr("src.providers.soundcloud.fetch_oembed", fake_oembed)
    card = asyncio.run(fetch_soundcloud_card("https://soundcloud.com/forss/flickermood"))

    assert card.title == "Flickermood"
    assert card.author_name == "Forss"
    assert card.hashtags == ["#soundcloud", "#music", "#forss"]
