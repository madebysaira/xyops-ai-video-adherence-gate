"""PURE heuristic engine (no ML) over grayscale frame dumps + media info."""

from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional

from .probe import MediaInfo

MOTION_STATIC_THR = 1.5
MOTION_JITTER_THR = 25.0
MORPH_SPIKE_MULT = 6.0
AUDIO_THR = -35.0
MIN_MOUTH_MOTION = 0.5


def load_gray(path: str) -> List[int]:
    """Read a grayscale raw dump into a flat list of pixel values (0-255)."""
    with open(path, "rb") as fh:
        data = fh.read()
    return list(data)


def mean_diff(a: List[int], b: List[int]) -> float:
    """Average absolute per-pixel difference over two equal-length lists."""
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    total = 0
    for i in range(n):
        total += abs(a[i] - b[i])
    return total / float(n)


def _diffs(frames_gray: List[List[int]]) -> List[float]:
    diffs: List[float] = []
    for i in range(1, len(frames_gray)):
        diffs.append(mean_diff(frames_gray[i - 1], frames_gray[i]))
    return diffs


def motion_health(
    frames_gray: List[List[int]], media: Optional[MediaInfo] = None
) -> Dict[str, Any]:
    """Classify overall motion health from consecutive frame diffs."""
    if len(frames_gray) < 2:
        return {
            "status": "STATIC",
            "mean_motion": 0.0,
            "min_motion": 0.0,
            "max_motion": 0.0,
            "motion_std": 0.0,
            "severity": "warn",
        }

    diffs = _diffs(frames_gray)
    mean = statistics.fmean(diffs) if diffs else 0.0
    mn = min(diffs) if diffs else 0.0
    mx = max(diffs) if diffs else 0.0
    std = statistics.pstdev(diffs) if len(diffs) > 1 else 0.0

    if mean < MOTION_STATIC_THR:
        status = "STATIC"
        severity = "fail"
    elif std > MOTION_JITTER_THR:
        status = "JITTER"
        severity = "warn"
    else:
        status = "OK"
        severity = "ok"

    return {
        "status": status,
        "mean_motion": round(mean, 4),
        "min_motion": round(mn, 4),
        "max_motion": round(mx, 4),
        "motion_std": round(std, 4),
        "severity": severity,
    }


def morph_drift(
    frames_gray: List[List[int]], media: Optional[MediaInfo] = None
) -> Dict[str, Any]:
    """Detect a spike in per-step diff indicating a sudden morph/scene change."""
    diffs = _diffs(frames_gray)
    if len(diffs) < 3:
        return {
            "status": "OK",
            "spike_at": None,
            "max_ratio": 0.0,
            "severity": "ok",
        }

    max_ratio = 0.0
    spike_at: Optional[int] = None
    for i in range(2, len(diffs)):
        prior = diffs[:i]
        median = statistics.median(prior)
        if median > 0:
            ratio = diffs[i] / median
        else:
            # Near-zero baseline: any clearly non-trivial jump is a spike.
            ratio = diffs[i] / 1.0 if diffs[i] > 5.0 else 0.0
        if ratio > max_ratio:
            max_ratio = ratio
            spike_at = i + 1  # index of the frame following the spike diff

    if spike_at is not None and max_ratio > MORPH_SPIKE_MULT:
        return {
            "status": "SPIKE",
            "spike_at": spike_at,
            "max_ratio": round(max_ratio, 4),
            "severity": "warn",
        }

    return {
        "status": "OK",
        "spike_at": None,
        "max_ratio": round(max_ratio, 4),
        "severity": "ok",
    }


def lipsync_health(
    media: Optional[MediaInfo],
    audio_rms: List[float],
    frames_gray: List[List[int]],
    mouth_motion: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """APPROXIMATE lip-sync health heuristic.

    Compares audio-active windows against frame motion; flags LIKELY_DESYNC when
    audio is active but frames are largely static. Clearly approximate.
    """
    if media is None or not media.has_audio or not audio_rms:
        return {"status": "NO_AUDIO", "severity": "ok", "note": "approximate"}

    active = [v for v in audio_rms if v > AUDIO_THR]
    if not active:
        return {
            "status": "NO_AUDIO",
            "severity": "ok",
            "note": "approximate (no audio above threshold)",
        }

    diffs = _diffs(frames_gray)
    mean_frame_motion = statistics.fmean(diffs) if diffs else 0.0

    if mean_frame_motion < MIN_MOUTH_MOTION:
        return {
            "status": "LIKELY_DESYNC",
            "severity": "warn",
            "note": "approximate",
            "mean_frame_motion": round(mean_frame_motion, 4),
            "audio_active_windows": len(active),
        }

    return {
        "status": "OK",
        "severity": "ok",
        "note": "approximate",
        "mean_frame_motion": round(mean_frame_motion, 4),
        "audio_active_windows": len(active),
    }