# Security

## Deployment Checklist

- Keep `.env` out of Git and restrict filesystem access to it.
- Set `BOT_ADMIN_IDS`; an empty value intentionally locks global controls.
- Use a random `DOWNLOAD_TOKEN_SECRET` with at least 32 characters.
- Publish `dropwire-web` only through HTTPS.
- Add reverse-proxy connection and request-rate limits for public deployments.
- Do not expose the SQLite database or the downloads volume directly.
- Keep `dropwire-web` bound to `127.0.0.1` when a reverse proxy runs on the host. Expose only Nginx ports 80 and 443.
- Do not enable access logging for `/download/`: signed URLs contain temporary bearer tokens.
- Keep Docker and the pinned Python dependencies updated.
- Leave containers non-root, read-only and without Linux capabilities.

## Implemented Controls

- Owner checks for global and provider settings.
- Optional user whitelist enforced for messages, commands and callback actions.
- Group-adder or live Telegram-admin checks for group settings.
- User ownership checks for DM settings and download callbacks.
- Atomic download request claiming and per-user active limits.
- Interrupted active downloads marked failed on startup so users cannot remain locked out.
- HMAC-signed expiring download links with traversal protection.
- Bounded external responses and media downloads.
- Trusted Twitter media CDN allowlist and validated redirects.
- Exact provider host matching to reject lookalike domains.
- HTML escaping for user, channel and group supplied text.
- No automatic retry after ambiguous Telegram upload timeouts.
- Trusted-host validation before Twitter media is placed in the inline cache.
- Uncached inline media is staged only in the requester's own DM, protected from forwarding and deleted immediately; SQLite stores only Telegram identifiers and technical dimensions.
- Group card deletion authorized against the original requester, bot owners or live group administrators.
- Delivery records expire after Telegram's 48-hour deletion window.
- Dependency vulnerability audit in the documented test flow.
- Read-only non-root containers with all Linux capabilities dropped and loopback-only web binding by default.

## Secrets

Tokens and API credentials remain deployment-level environment variables. Bot menus expose capability state only; they never display or store credential values. Rotate a token immediately if it appears in logs, screenshots or Git history.

## Reporting

Do not publish BOT_TOKEN values, signed download links or database files in an issue. Reproduce with redacted logs and include the provider, link shape and relevant timestamp.
