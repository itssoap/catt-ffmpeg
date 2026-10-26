"""Local ffmpeg/ffprobe helpers: list audio/subtitle tracks, extract a subtitle, remux an audio track."""

import atexit
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .error import CliError

# Subtitle codecs ffmpeg can convert to WebVTT. Bitmap formats (PGS, VobSub, DVB) cannot.
TEXT_SUB_CODECS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}
# Audio codecs Chromecasts play natively; anything else is transcoded to AAC.
CAST_AUDIO_CODECS = {"aac", "mp3", "ac3", "eac3", "opus", "vorbis", "flac"}


def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise CliError("{} not found in PATH; install ffmpeg to use track selection".format(name))
    return path


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    except subprocess.CalledProcessError as e:
        raise CliError("{} failed: {}".format(Path(cmd[0]).stem, e.stderr.strip()[-500:])) from e


def probe(path: str) -> dict[str, list[dict]]:
    """Return {"audio": [...], "subs": [...]}; track numbers are 1-based per type."""
    out = _run([_tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_streams", path])
    tracks: dict[str, list[dict]] = {"audio": [], "subs": []}
    for s in json.loads(out).get("streams", []):
        kind = {"audio": "audio", "subtitle": "subs"}.get(s.get("codec_type"))
        if kind:
            tags = s.get("tags", {})
            tracks[kind].append(
                {
                    "n": len(tracks[kind]) + 1,
                    "codec": s.get("codec_name", "?"),
                    "lang": tags.get("language", "und"),
                    "title": tags.get("title", ""),
                    "channels": s.get("channels"),
                    "default": bool(s.get("disposition", {}).get("default")),
                }
            )
    return tracks


def describe(kind: str, t: dict) -> str:
    extra = " {}ch".format(t["channels"]) if kind == "audio" and t["channels"] else ""
    note = ""
    if kind == "subs" and t["codec"] not in TEXT_SUB_CODECS:
        note = " (bitmap, cannot cast)"
    elif kind == "audio" and t["codec"] not in CAST_AUDIO_CODECS:
        note = " (will be transcoded to aac)"
    return "{}: [{}] {}{}{}{}{}".format(
        t["n"], t["lang"], t["codec"], extra, " " + t["title"] if t["title"] else "",
        " *default" if t["default"] else "", note,
    )


def _tmp(suffix: str) -> str:
    fd, name = tempfile.mkstemp(suffix=suffix, prefix="catt_")
    os.close(fd)
    atexit.register(lambda: Path(name).unlink(missing_ok=True))
    return name


def extract_subtitle(path: str, n: int, tracks: dict) -> str:
    """Convert embedded subtitle track n to a WebVTT temp file (what Chromecast accepts)."""
    if not 1 <= n <= len(tracks["subs"]):
        raise CliError("No subtitle track {} (file has {})".format(n, len(tracks["subs"])))
    if tracks["subs"][n - 1]["codec"] not in TEXT_SUB_CODECS:
        raise CliError("Subtitle track {} is bitmap-based and cannot be converted to WebVTT".format(n))
    out = _tmp(".vtt")
    _run([_tool("ffmpeg"), "-v", "error", "-y", "-i", path, "-map", "0:s:{}".format(n - 1), "-f", "webvtt", out])
    return out


def convert_subtitle_file(path: str) -> str:
    """Convert a standalone subtitle file (e.g. .ass/.ssa) to a WebVTT temp file."""
    out = _tmp(".vtt")
    _run([_tool("ffmpeg"), "-v", "error", "-y", "-i", path, "-f", "webvtt", out])
    return out


def remux_audio(path: str, n: int, tracks: dict) -> str:
    """Write a temp copy of the file with only the video and audio track n (same container)."""
    if not 1 <= n <= len(tracks["audio"]):
        raise CliError("No audio track {} (file has {})".format(n, len(tracks["audio"])))
    codec = "copy" if tracks["audio"][n - 1]["codec"] in CAST_AUDIO_CODECS else "aac"
    out = _tmp(Path(path).suffix or ".mkv")
    # ponytail: full remux to a temp file before casting (disk + wait); pipe-stream if that hurts.
    _run([
        _tool("ffmpeg"), "-v", "error", "-y", "-i", path,
        "-map", "0:v:0?", "-map", "0:a:{}".format(n - 1), "-c:v", "copy", "-c:a", codec, "-sn", out,
    ])
    return out
