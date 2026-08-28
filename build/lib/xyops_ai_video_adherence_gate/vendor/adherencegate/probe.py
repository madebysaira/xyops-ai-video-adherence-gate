"""ffprobe wrapper -> structured media info."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Optional


@dataclass
class MediaInfo:
    """Structured summary of a media file as reported by ffprobe."""

    width: Optional[int] = None
    height: Optional[int] = None
    codec_name: Optional[str] = None
    fps: Optional[float] = None
    duration: Optional[float] = None
    has_audio: bool = False
    audio_codec: Optional[str] = None
    channels: Optional[int] = None
    sample_rate: Optional[int] = None


def _parse_fps(r_frame_rate: Any) -> Optional[float]:
    """Convert an ffprobe r_frame_rate string ('num/den' or bare) to a float."""
    if not r_frame_rate:
        return None
    text = str(r_frame_rate)
    try:
        if "/" in text:
            num_s, den_s = text.split("/", 1)
            den = int(den_s)
            if den == 0:
                return None
            return float(Fraction(int(num_s), den))
        return float(text)
    except (ValueError, ZeroDivisionError):
        return None


def probe(path: str) -> MediaInfo:
    """Run ffprobe on ``path`` and return a populated :class:`MediaInfo`.

    Raises a clear ``RuntimeError`` if ffprobe fails or returns no data.
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=True
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise RuntimeError(
            f"ffprobe failed for {path!r}: {stderr or exc}"
        ) from exc
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe not found on PATH; install ffmpeg.") from exc

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ffprobe returned invalid JSON for {path!r}") from exc

    info = MediaInfo()

    for stream in data.get("streams", []):
        codec_type = stream.get("codec_type")
        if codec_type == "video" and info.width is None:
            info.width = _to_int(stream.get("width"))
            info.height = _to_int(stream.get("height"))
            info.codec_name = stream.get("codec_name")
            info.fps = _parse_fps(stream.get("r_frame_rate")) or _parse_fps(
                stream.get("avg_frame_rate")
            )
        elif codec_type == "audio" and not info.has_audio:
            info.has_audio = True
            info.audio_codec = stream.get("codec_name")
            info.channels = _to_int(stream.get("channels"))
            info.sample_rate = _to_int(stream.get("sample_rate"))

    fmt = data.get("format", {})
    if fmt.get("duration") is not None:
        try:
            info.duration = float(fmt["duration"])
        except (ValueError, TypeError):
            info.duration = None

    return info


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None