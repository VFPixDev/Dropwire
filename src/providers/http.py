"""Bound provider responses while streaming, including decoded response bodies."""

import httpx

from src.config import config


class ResponseTooLargeError(ValueError):
    pass


async def read_response_limited(response: httpx.Response, max_bytes: int) -> httpx.Response:
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            declared_size = int(content_length)
        except ValueError as exc:
            raise ResponseTooLargeError("Invalid provider Content-Length") from exc
        if declared_size < 0 or declared_size > max_bytes:
            raise ResponseTooLargeError("Provider response exceeds the configured limit")
    body = bytearray()
    async for chunk in response.aiter_bytes():
        if len(body) + len(chunk) > max_bytes:
            raise ResponseTooLargeError("Provider response exceeds the configured limit")
        body.extend(chunk)
    # aiter_bytes() has already decoded content encodings. Keeping gzip/br here
    # would make httpx decode the same content a second time.
    headers = {
        key: value for key, value in response.headers.items() if key not in {"content-encoding", "content-length"}
    }
    return httpx.Response(response.status_code, headers=headers, content=bytes(body), request=response.request)


async def request_provider(client: httpx.AsyncClient, url: str, *, method: str = "GET", **kwargs) -> httpx.Response:
    async with client.stream(method, url, **kwargs) as response:
        return await read_response_limited(response, config.PROVIDER_RESPONSE_MAX_KB * 1024)
