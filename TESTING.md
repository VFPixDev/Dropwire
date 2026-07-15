# Testing Dropwire

## Automated

```bash
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest tests -q
.venv/Scripts/python -m ruff check src tests
.venv/Scripts/python -m pip check
.venv/Scripts/python -m pip_audit -r requirements.txt
docker compose config --quiet
docker compose build
```

## Telegram Acceptance

1. Open `/start` in DM and verify Settings, Translation, Downloads and Help.
2. As the configured owner, open `/admin`, toggle one provider off and on, and verify the status text changes.
3. Send one public link from each provider and verify title, author, artwork/media, original button and hashtags.
4. Send `comment + link` and verify the sender quote. Repeat with name, username and mention modes.
5. Send two different supported links in one message and verify exactly one card per unique link.
6. Add the bot to a group. Verify a normal member cannot edit group settings or group translation.
7. Verify the bot adder and a Telegram administrator can edit that group from the bot DM.
8. Verify personal translation in a group affects only that user's links and group translation affects the group.
9. Start a YouTube download, choose a quality twice and verify only one job starts.
10. Open the signed link on iPhone Safari, download it, seek in the video and open it in the native player.
11. Open `/downloads` and verify a fresh link can be issued while the retained file exists.
12. Inspect `docker compose logs --tail 200`; there should be no tracebacks, leaked secrets or restart loop.

## Expected Limitations

- Twitter currently uses FxTwitter and automatically falls back from its JSON endpoint to HTML when necessary.
- Spotify author and duration require optional Spotify API credentials; basic cards do not.
- SoundCloud oEmbed does not always provide duration.
- Mobile downloads require a public HTTPS `WEB_BASE_URL`; `localhost` works only on the Docker host.
