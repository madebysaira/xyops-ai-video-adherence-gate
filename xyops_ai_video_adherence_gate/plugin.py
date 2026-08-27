#!/usr/bin/env python3
"""
xyOps Event Plugin: AI Video Adherence Gate
=============================================

Runs a rendered AI-video clip through AIVideoAdherenceGate as a *post-render
quality gate* inside an xyOps job or workflow. Emits the xyOps Wire Protocol
(JSON over STDOUT) so the platform can display progress, a results table, and a
final pass / warn / fail code that downstream workflow nodes can branch on.

Exit codes map to the gate's semantics:
    0  PASS  (all checks ok)
    1  WARN  (at least one warning, no failure)
    2  FAIL  (at least one failure -- or a warn with --strict)

Wire protocol reference: https://github.com/pixlcore/xyops/blob/main/docs/plugins.md
"""

from __future__ import annotations

import json
import os
import sys
import glob
import subprocess
import tempfile

# Make the vendored adherencegate package importable regardless of CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
_VENDOR = os.path.join(_HERE, "vendor")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

# Video extensions we look for when auto-discovering an input file.
VIDEO_EXTS = ("*.mp4", "*.mov", "*.webm", "*.mkv", "*.avi", "*.m4v", "*.gif")


def emit(obj: dict) -> None:
    """Print a single-line wire-protocol JSON envelope and flush immediately."""
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def read_job() -> dict:
    """Read the full job JSON document from STDIN (may be multi-chunk)."""
    chunks = []
    for chunk in sys.stdin:
        chunks.append(chunk)
    return json.loads("".join(chunks))


def find_video(job: dict) -> str | None:
    """Resolve the target video: explicit param > env > first input file in CWD."""
    params = job.get("params") or {}

    # 1) Explicit path parameter / environment variable.
    for key in ("video_path", "VIDEO_PATH", "video", "path"):
        val = params.get(key) or os.environ.get(key)
        if val and os.path.isfile(val):
            return val

    # 2) First input file declared on the job (already downloaded into CWD).
    for f in job.get("input", {}).get("files", []) or []:
        fn = f.get("filename", "")
        if fn.lower().endswith((".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".gif")):
            cand = os.path.join(os.getcwd(), fn)
            if os.path.isfile(cand):
                return cand

    # 3) Glob the job temp dir (CWD) for any video file.
    for ext in VIDEO_EXTS:
        hits = sorted(glob.glob(os.path.join(os.getcwd(), ext)))
        if hits:
            return hits[0]

    # 4) Fall back to a path supplied even if it does not exist yet (error later).
    for key in ("video_path", "VIDEO_PATH"):
        val = params.get(key) or os.environ.get(key)
        if val:
            return val
    return None


def severity_to_code(sev: str) -> int:
    return {"fail": 2, "warn": 1, "ok": 0}.get(sev, 1)


def main() -> int:
    try:
        job = read_job()
    except Exception as exc:  # malformed job doc
        emit({"xy": 1, "code": 2, "description": f"Could not parse job JSON: {exc}"})
        return 2

    emit({"xy": 1, "progress": 0.1, "status": "Locating rendered video..."})

    video = find_video(job)
    if not video:
        emit({
            "xy": 1, "code": 2,
            "description": "No video found. Set the 'video_path' parameter or attach an input video file.",
        })
        return 2
    if not os.path.isfile(video):
        emit({"xy": 1, "code": 2, "description": f"Video file not found: {video}"})
        return 2

    params = job.get("params") or {}
    prompt = params.get("prompt") or os.environ.get("PROMPT")
    vision_key = params.get("vision_key") or os.environ.get("VISION_KEY")
    vision_base_url = params.get("vision_base_url") or os.environ.get("VISION_BASE_URL")
    vision_model = params.get("vision_model") or os.environ.get("VISION_MODEL") or "gpt-4o-mini"
    strict = str(params.get("strict") or os.environ.get("STRICT", "")).lower() in ("1", "true", "yes")

    emit({"xy": 1, "progress": 0.4, "status": f"Running adherence gate on {os.path.basename(video)}..."})

    # Build CLI argv. Run the vendored gate as a subprocess so we capture the
    # structured JSON report cleanly (main() writes JSON to stdout and returns
    # an int exit code: 0 pass / 1 warn / 2 fail).
    cli_argv = [video, "--json"]
    if prompt:
        cli_argv += ["--prompt", prompt]
    if vision_key:
        cli_argv += ["--vision-key", vision_key]
    if vision_base_url:
        cli_argv += ["--vision-base-url", vision_base_url]
    if vision_model:
        cli_argv += ["--vision-model", vision_model]
    if strict:
        cli_argv += ["--strict"]

    proc = subprocess.run(
        [sys.executable, "-m", "adherencegate.cli", *cli_argv],
        cwd=_VENDOR, capture_output=True, text=True,
    )
    code = proc.returncode
    try:
        report = json.loads(proc.stdout.strip() or "{}")
    except Exception:
        report = {}

    # Compose a results table for the Job Details page.
    checks = report.get("checks", {})
    header = ["Check", "Status", "Detail"]
    rows = []
    for name, res in checks.items():
        status = res.get("status", "?")
        detail = res.get("severity", "")
        if name == "motion_health":
            detail = f"mean_motion={res.get('mean_motion')}"
        elif name == "morph_drift":
            detail = f"max_ratio={res.get('max_ratio')}"
        elif name == "lipsync_health":
            detail = res.get("status", "")
        elif name == "technical":
            detail = "; ".join(res.get("issues", [])) or res.get("status", "")
        rows.append([name, status, str(detail)])

    emit({
        "xy": 1, "progress": 0.95,
        "table": {
            "title": "AIVideoAdherenceGate Results",
            "header": header,
            "rows": rows,
            "caption": "Post-render semantic + motion health check.",
        },
    })

    label = {0: "PASS", 1: "WARN", 2: "FAIL"}.get(code, "WARN")
    emit({
        "xy": 1,
        "code": code,
        "description": f"AIVideoAdherenceGate: {label} for {os.path.basename(video)}",
    })
    return code


if __name__ == "__main__":
    sys.exit(main())
