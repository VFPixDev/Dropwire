# Dropwire

Dropwire — anything worth sharing, delivered to Telegram.

Dropwire is one Telegram bot that turns social links into compact media cards.

## Providers

- Twitter/X: text, photos, native GIF animations, video, stats, quotes, replies, polls and optional translation.
- YouTube: thumbnail, title, author, duration, date, stats and browser downloads.
- Spotify: artwork and title without credentials; richer metadata with optional API credentials.
- SoundCloud: artwork, title and author through the official oEmbed endpoint.

Every card can include source, media type and author hashtags. A comment before the first link is rendered as a sender quote. Multiple supported links in one message are handled in order.

Inline mode is supported after enabling it in BotFather: type `@dropwire_bot <link>` in any Telegram chat and select the generated result. Twitter/X uses Telegram Rich Messages for text above media, native multi-photo collages, quoted/replied-to post media and the original-link button in one message. GIF posts use native Telegram animation playback. Telegram does not expose the destination chat ID to inline bots, so inline results use the sender's DM settings over global defaults; group-specific settings cannot apply.

## Telegram UX

- `/start` - main menu.
- `/settings` - settings for the current context.
- `/downloads` - recent files that are still retained.
- `/help` - supported links and usage.
- `/status` - runtime status for the owner, settings for other users.
- `/admin` - owner-only provider controls and runtime counters.
- `/del` - in a group, reply to a Dropwire card to remove it. The original link sender and group administrators are allowed.

Settings are deliberately separated by scope:

- Global settings are available only to users listed in `BOT_ADMIN_IDS`.
- Group settings are edited in DM by the user who added the bot or a current Telegram group administrator.
- DM settings affect only that user's private chat.
- Inside a group, users can configure their own translation; group translation requires group admin rights.
- DM and group profiles can be reset to inherited global values.

## Quick Start

The release image is published as `ghcr.io/vfpixdev/dropwire`. For a private package, authenticate once with a GitHub token that has `read:packages`, then start the pinned release:

```bash
docker login ghcr.io
cp .env.example .env
# Set BOT_TOKEN, BOT_ADMIN_IDS and YOUTUBE_API_KEY.
DROPWIRE_IMAGE=ghcr.io/vfpixdev/dropwire:1.1.0 docker compose up -d
docker compose ps
```

To build from the checked-out source instead:

```bash
cp .env.example .env
# Set BOT_TOKEN, BOT_ADMIN_IDS and YOUTUBE_API_KEY.
docker build -t dropwire:local .
DROPWIRE_IMAGE=dropwire:local docker compose up -d
docker compose ps
```

Enable inline mode once in `@BotFather`: run `/setinline`, select `@dropwire_bot`, and set a placeholder such as `Вставьте ссылку из Twitter, YouTube, Spotify или SoundCloud`.

### Inline media cache

Rich inline messages can reuse only media already uploaded to Telegram. To enable Twitter collages:

1. Create a private Telegram channel, for example `Dropwire Cache`.
2. Add the bot as an administrator with permission to post messages.
3. Open the bot DM as a user listed in `BOT_ADMIN_IDS`.
4. Open `Settings` → `Global` → `Inline media cache` → `Bind channel`.
5. Forward any post from the private channel to the bot.

The channel stores media messages and SQLite stores their `file_id` values. If the channel is not configured or Telegram rejects a cached file, Dropwire automatically uses its compact inline fallback.

The web service is exposed on `http://localhost:8080` by default. YouTube browser links stay disabled until `WEB_BASE_URL` is a public HTTPS address that reaches this service.

### Nginx reverse proxy

The included [Nginx config](deploy/nginx/dropwire.conf) is intended for Nginx running on the Docker host. It exposes only signed download links, keeps the application port bound to localhost, and preserves HTTP Range requests required for seeking in iPhone Safari and the native player.

1. Replace every `dropwire.example.com` in `deploy/nginx/dropwire.conf` with your domain.
2. Issue a Let's Encrypt certificate, for example with `sudo certbot certonly --standalone -d your-domain.example`, and verify the certificate paths in the config.
3. Copy or link the config into `/etc/nginx/conf.d/dropwire.conf`.
4. Set `WEB_BASE_URL=https://your-domain.example` in `.env`.
5. Run `sudo nginx -t && sudo systemctl reload nginx`, then restart Dropwire.

Keep `WEB_BIND_ADDRESS=127.0.0.1` when Nginx runs on the host. If Nginx runs in Docker instead, connect it to `dropwire-network`, remove the host port mapping, and change the upstream to `dropwire-web:8080`.

For local development:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest tests -q
.venv/Scripts/python -m ruff check src tests
```

## Required Configuration

```env
BOT_TOKEN=123456789:replace_me
BOT_ADMIN_IDS=123456789
```

`BOT_ADMIN_IDS` is not a whitelist. Leave `TELEGRAM_USER_IDS` empty to allow everyone to use the bot.

YouTube cards require `YOUTUBE_API_KEY`. YouTube browser downloads also require:

```env
WEB_BASE_URL=https://dropwire.example.com
DOWNLOAD_TOKEN_SECRET=a-random-secret-with-at-least-32-characters
```

Put the web service behind HTTPS. Files are retained separately from link lifetime, so opening `/downloads` can issue a fresh signed link while the file still exists.

Optional richer Spotify metadata:

```env
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
```

Basic Spotify cards work without these credentials.

## iPhone Downloads

Video downloads are explicitly transcoded and verified before a link is sent:

- MP4 container.
- H.264 video.
- AAC stereo audio.
- `yuv420p` pixel format.
- `faststart` metadata placement.
- HTTP Range support for browser and native player seeking.

Audio-only downloads use M4A/AAC. Spotify and SoundCloud content is not downloaded.

## Supported Links

- `https://x.com/user/status/123`
- `https://twitter.com/user/status/123`
- `https://youtu.be/VIDEO_ID`
- `https://youtube.com/watch?v=VIDEO_ID`
- `https://youtube.com/shorts/VIDEO_ID`
- `https://open.spotify.com/track/ID`
- `https://spotify.link/...`
- `https://soundcloud.com/artist/track`
- `https://on.soundcloud.com/...`

See [SECURITY.md](SECURITY.md) and [TESTING.md](TESTING.md) before exposing the service publicly.
