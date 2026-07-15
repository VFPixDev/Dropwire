from src.services.youtube_downloader import YtDlpDownloader


def test_youtube_format_selector_prefers_iphone_safe_video(tmp_path):
    downloader = YtDlpDownloader(str(tmp_path / "downloads"))

    selector = downloader._build_format_selector("720")

    assert "vcodec^=avc1" in selector
    assert "acodec^=mp4a" in selector
    assert "ext=mp4" in selector


def test_youtube_audio_selector_prefers_m4a(tmp_path):
    downloader = YtDlpDownloader(str(tmp_path / "downloads"))

    selector = downloader._build_format_selector("audio")

    assert "ext=m4a" in selector
    assert "acodec^=mp4a" in selector


def test_iphone_transcode_command_guarantees_expected_codecs(tmp_path):
    downloader = YtDlpDownloader(str(tmp_path / "downloads"))
    command = downloader._build_iphone_ffmpeg_command(
        "ffmpeg",
        tmp_path / "source.webm",
        tmp_path / "ready.mp4",
    )

    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"
    assert command[command.index("-c:a") + 1] == "aac"
    assert command[command.index("-movflags") + 1] == "+faststart"
