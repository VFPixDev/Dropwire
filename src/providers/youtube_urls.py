import re
from urllib.parse import parse_qs, urlparse

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_video_id(url: str) -> str | None:
    try:
        parsed = urlparse(url.strip())
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 80, 443}
        ):
            return None
        host = (parsed.hostname or "").removeprefix("www.")
    except ValueError:
        return None

    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
        return candidate if VIDEO_ID_RE.fullmatch(candidate) else None

    if host in {"youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [None])[0]
            return video_id if video_id and VIDEO_ID_RE.fullmatch(video_id) else None

        if parsed.path.startswith("/shorts/"):
            candidate = parsed.path.split("/shorts/")[-1].split("/")[0]
            return candidate if VIDEO_ID_RE.fullmatch(candidate) else None

    return None
