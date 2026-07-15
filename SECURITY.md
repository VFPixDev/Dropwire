# Security

## Deployment Checklist

- Keep `.env` out of Git and restrict filesystem access to it.
- Set `BOT_ADMIN_IDS`; an empty value intentionally locks global controls.
- Use a random `DOWNLOAD_TOKEN_SECRET` with at least 32 characters.
- Publish `dropwire-web` only through HTTPS.
- Add reverse-proxy connection and request-rate limits for public deployments.
- Do not expose the SQLite database or the downloads volume directly.
- Keep Docker and the pinned Python dependencies updated.
- Leave containers non-root, read-only and without Linux capabilities.

## Implemented Controls

- Owner checks for global and provider settings.
- Group-adder or live Telegram-admin checks for group settings.
- User ownership checks for DM settings and download callbacks.
- Atomic download request claiming and per-user active limits.
- HMAC-signed expiring download links with traversal protection.
- Bounded external responses and media downloads.
- Trusted Twitter media CDN allowlist and validated redirects.
- Exact provider host matching to reject lookalike domains.
- HTML escaping for user, channel and group supplied text.
- No automatic retry after ambiguous Telegram upload timeouts.
- Dependency vulnerability audit in the documented test flow.

## Secrets

Tokens and API credentials remain deployment-level environment variables. Bot menus expose capability state only; they never display or store credential values. Rotate a token immediately if it appears in logs, screenshots or Git history.

## Reporting

Do not publish BOT_TOKEN values, signed download links or database files in an issue. Reproduce with redacted logs and include the provider, link shape and relevant timestamp.
