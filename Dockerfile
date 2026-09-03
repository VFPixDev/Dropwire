FROM python:3.14-alpine@sha256:c6ead215bfd31f1e433d968853b7a769989117115b728874824e6c0a27cb96fc

ARG ALPINE_MIRROR=https://dl-cdn.alpinelinux.org/alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN sed -i "s#https://dl-cdn.alpinelinux.org/alpine#${ALPINE_MIRROR}#" /etc/apk/repositories && \
    apk upgrade --no-cache && \
    apk add --no-cache ffmpeg

RUN adduser --disabled-password --uid 1000 botuser && \
    mkdir -p /tmp /app/data /app/downloads && \
    chown -R botuser:botuser /tmp /app/data /app/downloads

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN python -m pip install -r requirements.txt && \
    python -m pip uninstall --yes pip

COPY --chown=botuser:botuser src ./src

USER botuser

VOLUME ["/tmp", "/app/data", "/app/downloads"]

CMD ["python", "-m", "src.bot"]
