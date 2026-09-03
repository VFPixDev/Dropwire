# Testing Dropwire

## Automated

```bash
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest tests -q
.venv/Scripts/python -m ruff check .
.venv/Scripts/bandit -q -r src
.venv/Scripts/python -m pip check
.venv/Scripts/pip-audit -r requirements.txt
docker compose config --quiet
docker build -t dropwire:local .
docker scout cves dropwire:local --only-severity critical,high
```

Live provider and conversion checks use public sample links and never print credentials:

```bash
docker run --rm --env-file .env -v "${PWD}/scripts:/app/scripts:ro" dropwire:local python -m scripts.smoke_providers
docker run --rm --env-file .env -v "${PWD}/scripts:/app/scripts:ro" dropwire:local python -m scripts.smoke_inline
docker run --rm --env-file .env -v dropwire_data:/app/data -v "${PWD}/scripts:/app/scripts:ro" dropwire:local python -m scripts.smoke_rich
docker run --rm --env-file .env -v "${PWD}/scripts:/app/scripts:ro" --tmpfs /tmp:size=512m,mode=1777 dropwire:local python -m scripts.smoke_download
```

The same static, test, audit and container-build checks run in GitHub Actions on every push and pull request.

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
13. Connect a private technical cache channel from the owner settings and verify the bot has posting and deletion rights. Request previously uncached inline media and confirm no staging message remains in the channel.
14. Type `@dropwire_bot <public Twitter link>` in another chat and verify video plus photos appear in one Rich Message collage with the original button below it.
15. Verify a quoted post and a reply include the referenced post text and media inside one quotation block, with exactly one visual interval for a media-only post.
16. Verify a Twitter GIF plays as an animation and a normal video keeps its original aspect ratio.
17. In a group, reply `/del` to a card as its requester and verify the whole card/album is deleted while the original link remains. Verify another regular member cannot delete it and a group administrator can.

## Expected Limitations

- Twitter currently uses FxTwitter and automatically falls back from its JSON endpoint to HTML when necessary.
- Uncached inline Twitter media and YouTube thumbnails require a private technical cache channel. Staging messages are deleted immediately after Telegram returns reusable file identifiers; when the channel is unavailable, the bot uses a compact fallback.
- Spotify author and duration require optional Spotify API credentials; basic cards do not.
- SoundCloud oEmbed does not always provide duration.
- Mobile downloads require a public HTTPS `WEB_BASE_URL`; `localhost` works only on the Docker host.
18. Send a YouTube link and verify the full-size thumbnail, linked channel, absolute publication date and the `Open` / `Download` buttons in one row. Repeat through inline mode.
