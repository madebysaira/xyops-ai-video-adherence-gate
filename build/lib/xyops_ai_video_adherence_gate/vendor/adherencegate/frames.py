"""ffmpeg frame extraction and audio RMS window helpers."""

from __future__ import annotations

import os
import re
import subprocess
from typing import List, Optional

from .checks import load_gray
from .probe import MediaInfo, probe

GRAY_WIDTH = 32


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg/ffprobe not found on PATH; install ffmpeg.") from exc


def extract_frames(
    path: str, out_dir: str, count: int = 24, fps: Optional[float] = None
) -> List[str]:
    """Extract ``count`` evenly spaced color PNG frames (or ``fps`` sampling).

    Also produces a downscaled grayscale raw dump per frame for cheap pixel diffs.
    Returns the sorted list of color PNG frame paths.
    """
    os.makedirs(out_dir, exist_ok=True)

    if fps is not None and fps > 0:
        vf = f"fps={fps}"
    else:
        media = probe(path)
        duration = media.duration or 1.0
        # guard against zero/negative duration
        if duration <= 0:
            duration = 1.0
        # number of frames that will actually be emitted per second
        target_fps = max(1.0, float(count) / float(duration))
        vf = f"fps={target_fps}"

    frame_pattern = os.path.join(out_dir, "frame_%05d.png")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        path,
        "-vf",
        vf,
        frame_pattern,
    ]
    proc = _run(cmd)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extraction failed: {proc.stderr.strip()}")

    color_frames = sorted(
        os.path.join(out_dir, name)
        for name in os.listdir(out_dir)
        if name.startswith("frame_") and name.endswith(".png")
    )

    # Emit downscaled grayscale raw dumps for the checks engine.
    _dump_gray(path, out_dir, vf)

    return color_frames


def _dump_gray(path: str, out_dir: str, vf: str) -> None:
    """Extract the same frames as grayscale raw video, writing gray_XXXXX.raw."""
    gray_pattern = os.path.join(out_dir, "gray_%05d.raw")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        path,
        "-vf",
        f"{vf},scale={GRAY_WIDTH}:-1,format=gray",
        "-pix_fmt",
        "gray",
        "-f",
        "image2",
        gray_pattern,
    ]
    proc = _run(cmd)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg grayscale dump failed: {proc.stderr.strip()}")


def load_gray_files(out_dir: str) -> List[List[int]]:
    """Load all gray_*.raw dumps in ``out_dir`` into grayscale value lists."""
    gray_files = sorted(
        os.path.join(out_dir, name)
        for name in os.listdir(out_dir)
        if name.startswith("gray_") and name.endswith(".raw")
    )
    return [load_gray(gf) for gf in gray_files]


def audio_rms_windows(path: str, windows: int = 12) -> List[float]:
    """Return per-window mean volume (dB) values; [] if no audio or on failure.

    Each window is analyzed with ffmpeg ``volumedetect``. Values are the
    ``mean_volume`` reported in dB (more negative == quieter).
    """
    try:
        media = probe(path)
    except RuntimeError:
        return []

    if not media.has_audio or media.duration is None or media.duration <= 0:
        return []

    if windows <= 0:
        return []

    step = media.duration / float(windows)
    means: List[float] = []
    for i in range(windows):
        start = i * step
        cmd = [
            "ffmpeg",
            "-ss",
            str(start),
            "-t",
            str(step),
            "-i",
            path,
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ]
        proc = _run(cmd)
        text = proc.stderr or ""
        m = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", text)
        if m:
            try:
                means.append(float(m.group(1)))
            except ValueError:
                means.append(-91.0)
        else:
            means.append(-91.0)
    return means