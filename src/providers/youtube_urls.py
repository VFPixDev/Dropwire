import re
from urllib.parse import parse_qs, urlparse

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_video_id(url: str) -> str | None:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().replace("www.", "")

    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
        return candidate if VIDEO_ID_RE.match(candidate) else None

    if host in {"youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [None])[0]
            return video_id if video_id and VIDEO_ID_RE.match(video_id) else None

        if parsed.path.startswith("/shorts/"):
            candidate = parsed.path.split("/shorts/")[-1].split("/")[0]
            return candidate if VIDEO_ID_RE.match(candidate) else None

    return None
