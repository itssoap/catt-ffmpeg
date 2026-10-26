import json
from unittest import mock

import pytest

from catt import ffmpeg
from catt.error import CliError

PROBE = {
    "streams": [
        {"codec_type": "video", "codec_name": "h264"},
        {"codec_type": "audio", "codec_name": "dts", "channels": 6, "tags": {"language": "eng"}},
        {"codec_type": "audio", "codec_name": "aac", "disposition": {"default": 1}},
        {"codec_type": "subtitle", "codec_name": "hdmv_pgs_subtitle"},
        {"codec_type": "subtitle", "codec_name": "ass", "tags": {"language": "fre"}},
    ]
}


def tracks():
    with mock.patch.object(ffmpeg, "_tool", return_value="ffprobe"), mock.patch.object(
        ffmpeg, "_run", return_value=json.dumps(PROBE)
    ):
        return ffmpeg.probe("x.mkv")


def test_probe_numbers_tracks_per_type():
    t = tracks()
    assert [a["n"] for a in t["audio"]] == [1, 2]
    assert [s["codec"] for s in t["subs"]] == ["hdmv_pgs_subtitle", "ass"]
    assert t["audio"][1]["default"]


def test_bitmap_sub_and_bad_numbers_rejected():
    t = tracks()
    with pytest.raises(CliError):
        ffmpeg.extract_subtitle("x.mkv", 1, t)
    with pytest.raises(CliError):
        ffmpeg.extract_subtitle("x.mkv", 3, t)
    with pytest.raises(CliError):
        ffmpeg.remux_audio("x.mkv", 3, t)
