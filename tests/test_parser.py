from src.twitter.parser import parse_tweet_html


def test_parse_tweet_html_strips_translation_header_from_text_and_extracts_language():
    html = """
    <html>
      <head>
        <meta property="og:title" content="sufufle (@sufufle)" />
        <meta property="og:description" content="📑 Перекладено з англійської<br><br>З Днем святого Валентина<br><br>[ #цинонари #цино #тигнари #GenshinImpact ]" />
        <meta property="article:published_time" content="2026-02-14T12:19:00Z" />
      </head>
      <body></body>
    </html>
    """

    tweet = parse_tweet_html(html, "https://x.com/sufufle/status/2022646767851118595")

    assert tweet is not None
    assert "Перекладено з" not in tweet.text
    assert tweet.text.startswith("З Днем святого Валентина")
    assert tweet.source_language == "англійської"
    assert tweet.translated_text is not None
    assert tweet.translated_text.startswith("З Днем святого Валентина")


def test_parse_tweet_html_extracts_source_language_from_french_header():
    html = """
    <html>
      <head>
        <meta property="og:title" content="sufufle (@sufufle)" />
        <meta property="og:description" content="📑 Traduit de l’anglais<br><br>Joyeuse Saint-Valentin<br><br>[ #cynonari #cyno #tighnari #GenshinImpact ]" />
        <meta property="article:published_time" content="2026-02-14T12:19:00Z" />
      </head>
      <body></body>
    </html>
    """

    tweet = parse_tweet_html(html, "https://x.com/sufufle/status/2022646767851118595")

    assert tweet is not None
    assert "Traduit de" not in tweet.text
    assert tweet.text.startswith("Joyeuse Saint-Valentin")
    assert tweet.source_language == "l'anglais"
    assert tweet.translated_text is not None
    assert tweet.translated_text.startswith("Joyeuse Saint-Valentin")


def test_parse_tweet_html_attaches_video_thumbnail_without_duplicate_photo():
    html = """
    <html><head>
      <meta property="og:title" content="Example (@example)" />
      <meta property="og:description" content="Video post" />
      <meta property="article:published_time" content="2026-07-31T12:00:00Z" />
      <meta property="og:video" content="https://video.twimg.com/ext_tw_video/123/video.mp4" />
      <meta property="og:image" content="https://pbs.twimg.com/ext_tw_video_thumb/123/pu/img/preview.jpg" />
    </head></html>
    """

    tweet = parse_tweet_html(html, "https://x.com/example/status/123")

    assert tweet is not None
    assert len(tweet.media) == 1
    assert tweet.media[0].type == "video"
    assert tweet.media[0].thumbnail_url == "https://pbs.twimg.com/ext_tw_video_thumb/123/pu/img/preview.jpg"


def test_parse_tweet_html_collects_repeated_and_indexed_image_meta():
    html = """
    <html><head>
      <meta property="og:title" content="Gallery (@gallery)" />
      <meta property="og:description" content="Four photos" />
      <meta property="og:image" content="https://pbs.twimg.com/media/one.jpg" />
      <meta property="og:image" content="https://pbs.twimg.com/media/two.jpg" />
      <meta name="twitter:image:1" content="https://pbs.twimg.com/media/three.jpg" />
      <meta property="og:image:2" content="https://pbs.twimg.com/media/four.jpg" />
    </head></html>
    """

    tweet = parse_tweet_html(html, "https://x.com/gallery/status/123")

    assert tweet is not None
    assert [item.url for item in tweet.media] == [
        "https://pbs.twimg.com/media/one.jpg",
        "https://pbs.twimg.com/media/two.jpg",
        "https://pbs.twimg.com/media/three.jpg",
        "https://pbs.twimg.com/media/four.jpg",
    ]


def test_parse_tweet_html_expands_fxtwitter_mosaic():
    html = """
    <html><head>
      <meta property="og:title" content="Gallery (@gallery)" />
      <meta property="og:description" content="Mosaic" />
      <meta property="og:image" content="https://mosaic.fxtwitter.com/123/Photo_A/Photo-B" />
    </head></html>
    """

    tweet = parse_tweet_html(html, "https://x.com/gallery/status/123")

    assert tweet is not None
    assert [item.url for item in tweet.media] == [
        "https://pbs.twimg.com/media/Photo_A?format=jpg&name=orig",
        "https://pbs.twimg.com/media/Photo-B?format=jpg&name=orig",
    ]
