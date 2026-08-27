# Dropwire Release Status

## Ready

- Twitter/X, YouTube, Spotify and SoundCloud cards.
- Aiogram 3.31 runtime with Telegram Bot API 10.3 Rich Messages.
- Twitter inline collages, GIF animations, quoted posts and replies with transient requester-DM staging and reusable Telegram file identifiers.
- Group `/del` ownership and administrator checks for removing complete generated cards.
- Global, group and DM settings with scope-specific controls.
- Owner panel and provider switches.
- Group management for bot adders and current Telegram administrators.
- YouTube quality selection, queue, progress, history and signed browser links.
- Verified iPhone-compatible MP4/H.264/AAC output and M4A audio.
- Scheduled file cleanup, request limits and duplicate-request protection.
- Docker hardening, web healthcheck and security headers.
- Automated tests, live provider smoke tests and dependency vulnerability audit.

## Deployment Tasks

- Set a public HTTPS `WEB_BASE_URL` to enable download buttons for phones outside the Docker host.
- Set a dedicated `DOWNLOAD_TOKEN_SECRET` instead of relying on the BOT_TOKEN fallback.
- Optionally add Spotify API credentials for richer metadata.
- Run the Telegram acceptance checklist in `TESTING.md` after deployment.
- Bind a private channel in Global settings to enable Rich inline media collages.

## Future, Not Release Blocking

- Persistent distributed download queue for multi-host deployments.
- Object storage for large installations.
- Metrics export for Prometheus/OpenTelemetry.
- Localization of bot menu copy beyond Russian.
