import json
from types import SimpleNamespace

from src.media.compress import VideoMetadata, _needs_compatibility_transcode, probe_video


def test_non_square_pixels_require_compatibility_transcode():
    metadata = VideoMetadata(
        width=720,
        height=1280,
        video_codec="h264",
        pixel_format="yuv420p",
        sample_aspect_ratio="4:3",
    )

    assert _needs_compatibility_transcode(metadata, is_animation=False) is True


def test_iphone_compatible_video_does_not_require_transcode():
    metadata = VideoMetadata(
        width=720,
        height=1280,
        video_codec="h264",
        audio_codec="aac",
        pixel_format="yuv420p",
        sample_aspect_ratio="1:1",
    )

    assert _needs_compatibility_transcode(metadata, is_animation=False) is False


def test_probe_video_reads_geometry_and_rotation(monkeypatch):
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "pix_fmt": "yuv420p",
                "width": 1080,
                "height": 1920,
                "sample_aspect_ratio": "1:1",
                "duration": "3.6",
                "side_data_list": [{"rotation": -90}],
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ]
    }
    monkeypatch.setattr("src.media.compress.shutil.which", lambda name: "ffprobe")
    monkeypatch.setattr(
        "src.media.compress.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(payload).encode()),
    )

    metadata = probe_video("clip.mp4")

    assert metadata is not None
    assert metadata.width == 1080
    assert metadata.height == 1920
    assert metadata.duration == 4
    assert metadata.rotation == 270
