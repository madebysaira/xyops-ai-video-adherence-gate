"""Command-line interface for AIVideoAdherenceGate."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from typing import Any, Dict, Optional

from . import __version__
from . import checks
from . import frames
from . import report
from .probe import probe


def _technical_check(media) -> Dict[str, Any]:
    problems = []
    severity = "ok"
    if media.duration is None or media.duration <= 0:
        problems.append("missing duration")
        severity = "fail"
    if media.width is None or media.height is None:
        problems.append("missing resolution")
        severity = "fail"
    if not media.has_audio:
        # Silent video is common/valid for AI clips; warn, don't hard-fail.
        problems.append("no audio stream")
        severity = "warn"

    status = "OK" if not problems else ("FAIL" if severity == "fail" else "WARN")
    return {
        "status": status,
        "severity": severity,
        "issues": problems,
        "width": media.width,
        "height": media.height,
        "codec_name": media.codec_name,
        "fps": media.fps,
        "duration": media.duration,
        "has_audio": media.has_audio,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adherencegate",
        description="AIVideoAdherenceGate: post-render semantic + motion health gate.",
    )
    parser.add_argument("video", help="path to the rendered video clip")
    parser.add_argument("--prompt", help="creative contract prompt for vision scoring")
    parser.add_argument("--vision-key", help="OpenAI-compatible API key")
    parser.add_argument("--vision-base-url", help="OpenAI-compatible base URL")
    parser.add_argument("--vision-model", default="gpt-4o-mini")
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    parser.add_argument("--markdown", metavar="FILE", help="write markdown report to FILE")
    parser.add_argument("--frames", type=int, default=24, help="number of frames to sample")
    parser.add_argument(
        "--strict", action="store_true", help="treat warnings as failures (exit 2)"
    )
    parser.add_argument(
        "--no-vision", action="store_true", help="force-skip vision scoring"
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    video = args.video
    if not os.path.exists(video):
        print(f"error: video file not found: {video}", file=sys.stderr)
        return 2

    try:
        media = probe(video)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    results: Dict[str, Any] = {}

    results["technical"] = _technical_check(media)

    try:
        with tempfile.TemporaryDirectory(prefix="adherencegate_") as tmp:
            frame_paths = frames.extract_frames(video, tmp, count=args.frames)
            gray = frames.load_gray_files(tmp)

            results["motion_health"] = checks.motion_health(gray, media)
            results["morph_drift"] = checks.morph_drift(gray, media)

            audio_rms = frames.audio_rms_windows(video)
            results["lipsync_health"] = checks.lipsync_health(
                media, audio_rms, gray, None
            )

            if not args.no_vision and args.prompt:
                from . import vision

                score = vision.score_contract(
                    args.prompt,
                    frame_paths,
                    api_key=args.vision_key,
                    base_url=args.vision_base_url,
                    model=args.vision_model,
                )
                if score is not None:
                    score["severity"] = (
                        "fail"
                        if not score.get("subject_present")
                        else ("ok" if score.get("score_0_1", 0) >= 0.7 else "warn")
                    )
                    results["vision_adherence"] = score
                else:
                    results["vision_adherence"] = {
                        "status": "SKIPPED",
                        "severity": "ok",
                        "note": "no API key or openai unavailable",
                    }
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    verdict = report.make_verdict(results)
    severity = verdict.severity

    if args.markdown:
        with open(args.markdown, "w") as fh:
            fh.write(report.to_markdown(verdict, video, args.prompt))

    if args.json:
        print(report.to_json(verdict, video, args.prompt))
    else:
        print(report.to_markdown(verdict, video, args.prompt))

    if severity == "fail":
        return 2
    if severity == "warn":
        return 2 if args.strict else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())