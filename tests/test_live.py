"""Public live counters: bump persists, unknown keys fail."""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server


def main() -> int:
    assert server.STATS == ROOT / "data" / "stats.json"
    d = Path(tempfile.mkdtemp())
    server.STATS = d / "stats.json"
    a = server.bump("visits")
    assert a == {"visits": 1, "invite": 0, "project": 0, "wink": 0}, a
    b = server.bump("wink")
    assert b["wink"] == 1 and b["visits"] == 1, b
    c = server.bump("wink")
    assert c["wink"] == 2, c
    try:
        server.bump("nope")
        raise AssertionError("bad key passed")
    except ValueError:
        pass
    on_disk = json.loads(server.STATS.read_text(encoding="utf-8"))
    assert on_disk["wink"] == 2
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
