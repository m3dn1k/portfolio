"""Optional neural-net hook. Fail-open: down or unset never drops a lead."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

TIMEOUT = 90


def analyze(payload: dict) -> dict | None:
    url = (os.environ.get("NN_URL") or "").strip()
    if not url:
        return None
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    analytics = str(data.get("analytics") or "").strip()
    if not analytics:
        return None
    return {"analytics": analytics}
