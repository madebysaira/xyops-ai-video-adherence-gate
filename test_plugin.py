#!/usr/bin/env python3
"""End-to-end test for the xyOps AI Video Adherence Gate plugin.

Simulates xyOps launching the plugin as a job: writes a synthetic video into a
temp CWD, pipes a job JSON document to the plugin over STDIN, and asserts the
plugin emits valid xyOps Wire Protocol JSON (progress/status/table + a final
complete line with code 0/1/2).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.join(HERE, "xyops_ai_video_adherence_gate", "plugin.py")
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


def _make_clip(path: str, kind: str) -> None:
    if kind == "static":
        cmd = [FFMPEG, "-y", "-f", "lavfi", "-i", "color=c=blue:s=128x128:d=2",
               "-pix_fmt", "yuv420p", path]
    else:  # motion: panned testsrc
        cmd = [FFMPEG, "-y", "-f", "lavfi",
               "-i", "testsrc=size=320x128:rate=15:duration=2",
               "-vf", "crop=128:128:x='n*8':y=0,format=yuv420p", path]
    subprocess.run(cmd, capture_output=True, check=True)


def _run_plugin(video_path: str, params: dict | None = None) -> list[dict]:
    """Run the plugin with a simulated job; return parsed STDOUT JSON lines."""
    work = tempfile.mkdtemp(prefix="xyops-plugin-test_")
    try:
        clip = os.path.join(work, "render.mp4")
        _make_clip(clip, video_path)
        job = {
            "xy": 1,
            "type": "event",
            "params": params or {},
            "input": {"data": {}, "files": [{"filename": "render.mp4"}]},
        }
        proc = subprocess.run(
            [sys.executable, PLUGIN],
            input=json.dumps(job),
            cwd=work,
            capture_output=True, text=True,
        )
        lines = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
        return proc.returncode, lines
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_plugin_emits_protocol_and_completes():
    rc, lines = _run_plugin("motion")
    # At least one progress/status line, plus a final complete line with code.
    assert lines, "plugin produced no STDOUT JSON"
    complete = [l for l in lines if "code" in l]
    assert complete, "plugin never sent a completion (code) line"
    final = complete[-1]
    assert final.get("xy") == 1
    assert final["code"] in (0, 1, 2)
    # A results table should be present.
    assert any("table" in l for l in lines), "no results table emitted"


def test_static_clip_fails_or_warns():
    rc, lines = _run_plugin("static")
    complete = [l for l in lines if "code" in l][-1]
    # A silent, static clip is at least a WARN (1) or FAIL (2), never PASS (0 with audio).
    assert complete["code"] in (1, 2), f"unexpected code {complete['code']}"


def test_missing_video_reports_error():
    work = tempfile.mkdtemp(prefix="xyops-plugin-err_")
    try:
        job = {"xy": 1, "type": "event", "params": {"video_path": "/no/such/file.mp4"},
               "input": {"data": {}, "files": []}}
        proc = subprocess.run([sys.executable, PLUGIN], input=json.dumps(job),
                               cwd=work, capture_output=True, text=True)
        lines = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
        final = [l for l in lines if "code" in l][-1]
        assert final["code"] == 2
        assert "not found" in final.get("description", "").lower()
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
