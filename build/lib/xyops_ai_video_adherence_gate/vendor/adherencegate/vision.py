"""OPTIONAL OpenAI-compatible vision scorer (lazy, defensive)."""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Dict, List, Optional


def _encode_data_url(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except OSError:
        return None


def score_contract(
    prompt: str,
    frame_paths: List[str],
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: str = "gpt-4o-mini",
) -> Optional[Dict[str, Any]]:
    """Score prompt-vs-clip adherence using a vision model, or return None.

    Uses the OpenAI-compatible client (lazy import). Returns the parsed JSON
    contract dict or ``None`` on any error / if no key is available.
    """
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        return None

    data_urls = [u for u in (_encode_data_url(p) for p in frame_paths[:4]) if u]
    if not data_urls:
        return None

    try:
        from openai import OpenAI  # lazy import
    except Exception:
        return None

    try:
        client = OpenAI(api_key=key, base_url=base_url or "https://api.openai.com/v1")

        content: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "You are a video-adherence checker. Compare the supplied "
                    "frames to the creative contract below and report, as JSON: "
                    '{"subject_present": bool, "action_present": bool, '
                    '"camera_match": bool, "score_0_1": float, "notes": str}. '
                    "Contract: " + prompt
                ),
            }
        ]
        for url in data_urls:
            content.append({"type": "image_url", "image_url": {"url": url}})

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content
        return json.loads(text) if text else None
    except Exception:
        return None