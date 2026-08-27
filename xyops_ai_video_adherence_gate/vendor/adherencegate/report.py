"""Verdict aggregation and report formatting."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

_SEVERITY_ORDER = {"ok": 0, "warn": 1, "fail": 2}


@dataclass
class Verdict:
    severity: str = "ok"
    checks: Dict[str, Any] = field(default_factory=dict)


def aggregate(results: Dict[str, Any]) -> str:
    """Return the worst severity among all check results ('fail' > 'warn' > 'ok')."""
    worst = "ok"
    for result in results.values():
        sev = result.get("severity", "ok") if isinstance(result, dict) else "ok"
        if _SEVERITY_ORDER.get(sev, 0) > _SEVERITY_ORDER.get(worst, 0):
            worst = sev
    return worst


def make_verdict(results: Dict[str, Any]) -> Verdict:
    return Verdict(severity=aggregate(results), checks=results)


def to_markdown(
    verdict: Verdict, path: str, prompt: Optional[str] = None
) -> str:
    lines = [
        "# AIVideoAdherenceGate Report",
        "",
        f"- **File:** `{path}`",
        f"- **Overall severity:** `{verdict.severity}`",
    ]
    if prompt:
        lines.append(f"- **Prompt:** {prompt}")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    if not verdict.checks:
        lines.append("_No checks run._")
    for name, result in verdict.checks.items():
        if isinstance(result, dict):
            sev = result.get("severity", "ok")
            lines.append(f"### {name} — `{result.get('status', sev)}` ({sev})")
            for k, v in result.items():
                if k in ("severity", "status"):
                    continue
                lines.append(f"- **{k}:** {v}")
        else:
            lines.append(f"### {name}")
            lines.append(f"- {result}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def to_json(verdict: Verdict, path: str, prompt: Optional[str] = None) -> str:
    payload: Dict[str, Any] = {"path": path, "severity": verdict.severity, "checks": verdict.checks}
    if prompt:
        payload["prompt"] = prompt
    return json.dumps(payload, indent=2)