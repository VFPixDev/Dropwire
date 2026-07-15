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
