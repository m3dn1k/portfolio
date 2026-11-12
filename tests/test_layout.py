"""Resize the live page and fail if layout or photos spill."""
from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
# width sweep at a fixed height, plus the screens we actually care about
WIDTHS = (320, 360, 375, 390, 414, 480, 640, 767, 768, 900, 1024, 1280, 1440, 1920)
HEIGHT = 900
SCREENS = (
    (390, 844),  # phone
    (430, 932),
    (768, 1024),  # tablet
    (1024, 768),
    (1366, 768),  # 16:9
    (1920, 1080),
    (2560, 1440),  # widescreen
    (2560, 1080),  # 21:9
    (3440, 1440),
)
SLACK = 2

PROBE = r"""
(() => {
  const slack = 2;
  const vw = innerWidth;
  const bad = [];
  const skip = (el) => el.classList?.contains("skip") || el.closest?.(".skip");
  for (const el of document.querySelectorAll("body *")) {
    if (skip(el)) continue;
    const st = getComputedStyle(el);
    if (st.display === "none" || st.visibility === "hidden") continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    if (r.right > vw + slack) {
      bad.push((el.className || el.tagName) + " right=" + Math.round(r.right) + " vw=" + vw);
      if (bad.length >= 8) break;
    }
  }
  const imgs = [...document.querySelectorAll("img")].map((img) => {
    const r = img.getBoundingClientRect();
    const p = img.parentElement.getBoundingClientRect();
    const leak =
      r.left < p.left - slack ||
      r.right > p.right + slack ||
      r.top < p.top - slack ||
      r.bottom > p.bottom + slack;
    return {
      src: img.getAttribute("src"),
      ok: img.complete && img.naturalWidth > 0,
      nw: img.naturalWidth,
      w: Math.round(r.width),
      h: Math.round(r.height),
      leak,
      parent: img.parentElement.className,
    };
  });
  const nav = document.querySelector(".nav").getBoundingClientRect();
  const idle = document.querySelector(".hero-avatar-idle").getBoundingClientRect();
  const wink = document.querySelector(".hero-avatar-wink").getBoundingClientRect();
  const cases = [...document.querySelectorAll(".case")].map((block) => {
    const shotsEl = block.querySelector(".case-shots");
    const copyEl = block.querySelector(".case-copy");
    if (!shotsEl || !copyEl) return null;
    const shots = shotsEl.getBoundingClientRect();
    const copy = copyEl.getBoundingClientRect();
    const shotImgs = [...shotsEl.querySelectorAll("img")].map((img) => {
      const r = img.getBoundingClientRect();
      const fit = getComputedStyle(img).objectFit;
      const boxAr = r.width / r.height;
      const natAr = img.naturalWidth / img.naturalHeight;
      return {
        src: img.getAttribute("src"),
        on: img.classList.contains("is-on"),
        ui: img.classList.contains("case-shot-ui"),
        photo: img.classList.contains("case-shot-photo"),
        fit,
        crops: fit === "cover" && Math.abs(boxAr - natAr) / natAr > 0.03,
        inside:
          r.left >= shots.left - slack &&
          r.right <= shots.right + slack &&
          r.top >= shots.top - slack &&
          r.bottom <= shots.bottom + slack,
        w: Math.round(r.width),
        h: Math.round(r.height),
      };
    });
    return {
      shotImgs,
      shots: { w: Math.round(shots.width), h: Math.round(shots.height), t: Math.round(shots.top), b: Math.round(shots.bottom) },
      copy: { t: Math.round(copy.top), h: Math.round(copy.height), l: Math.round(copy.left) },
    };
  }).filter(Boolean);
  const first = cases[0];
  return {
    vw,
    scrollExtra: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    bad,
    imgs,
    cases,
    shotImgs: first.shotImgs,
    shots: first.shots,
    copy: first.copy,
    navW: Math.round(nav.width),
    winkMatch: Math.abs(idle.width - wink.width) < 3 && Math.abs(idle.height - wink.height) < 3,
    idleW: Math.round(idle.width),
    idleH: Math.round(idle.height),
  };
})()
"""


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _browser() -> Path:
    for p in (
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/google-chrome-stable"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
    ):
        if p.is_file():
            return p
    raise FileNotFoundError("Chrome or Edge not found")


class Cdp:
    def __init__(self, ws_url: str):
        from urllib.parse import urlparse

        u = urlparse(ws_url)
        self.sock = socket.create_connection((u.hostname, u.port or 80), timeout=20)
        key = __import__("base64").b64encode(os.urandom(16)).decode()
        path = u.path + (("?" + u.query) if u.query else "")
        self.sock.sendall(
            (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {u.netloc}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n"
                "\r\n"
            ).encode()
        )
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("cdp handshake closed")
            buf += chunk
        head, rest = buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise RuntimeError(head.decode("latin1", "replace")[:240])
        self._buf = rest
        self._n = 0

    def _pull(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(max(4096, n - len(self._buf)))
            if not chunk:
                raise EOFError("cdp socket")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _send(self, obj: dict) -> None:
        data = json.dumps(obj).encode()
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        hdr = bytearray([0x81])
        n = len(data)
        if n < 126:
            hdr.append(0x80 | n)
        elif n < 65536:
            hdr.append(0x80 | 126)
            hdr += struct.pack("!H", n)
        else:
            hdr.append(0x80 | 127)
            hdr += struct.pack("!Q", n)
        self.sock.sendall(bytes(hdr) + mask + masked)

    def _recv(self) -> dict:
        while True:
            b1, b2 = self._pull(2)
            op = b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._pull(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._pull(8))[0]
            if b2 & 0x80:
                mask = self._pull(4)
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(self._pull(n)))
            else:
                data = self._pull(n)
            if op == 0x9:
                self._send_pong(data)
                continue
            if op == 0x8:
                raise EOFError("cdp closed")
            if op == 0x1:
                return json.loads(data.decode())

    def _send_pong(self, data: bytes) -> None:
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        n = len(data)
        hdr = bytearray([0x8A, 0x80 | n] if n < 126 else [0x8A, 0x80 | 126])
        if n >= 126:
            hdr += struct.pack("!H", n)
        self.sock.sendall(bytes(hdr) + mask + masked)

    def call(self, method: str, params: dict | None = None) -> dict:
        self._n += 1
        nid = self._n
        self._send({"id": nid, "method": method, "params": params or {}})
        while True:
            msg = self._recv()
            if msg.get("id") == nid:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result") or {}

    def eval(self, expr: str, await_promise: bool = False):
        r = self.call(
            "Runtime.evaluate",
            {"expression": expr, "returnByValue": True, "awaitPromise": await_promise},
        )
        if r.get("exceptionDetails"):
            raise RuntimeError(r["exceptionDetails"])
        return r["result"].get("value")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def _serve() -> tuple[ThreadingHTTPServer, str]:
    port = _free_port()

    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(ROOT), **k)

        def log_message(self, *_a) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{port}/"


def _wait_json(url: str, tries: int = 50) -> dict:
    last = None
    for _ in range(tries):
        try:
            with urlopen(url, timeout=1) as r:
                return json.loads(r.read().decode())
        except OSError as e:
            last = e
            time.sleep(0.1)
    raise RuntimeError(last)


def _check(rep: dict, width: int) -> None:
    w = rep["vw"]
    assert abs(w - width) <= 1, (width, w)
    assert rep["scrollExtra"] <= SLACK, (width, "h-scroll", rep["scrollExtra"], rep["bad"])
    assert not rep["bad"], (width, "overflow", rep["bad"])
    assert rep["navW"] >= width - 16, (width, "nav", rep["navW"])
    assert rep["winkMatch"] and rep["idleW"] > 40 and rep["idleH"] > 40, (width, "avatar", rep)
    for im in rep["imgs"]:
        assert im["ok"] and im["nw"] > 0, (width, "img dead", im)
        assert im["w"] > 8 and im["h"] > 8, (width, "img tiny", im)
        assert not im["leak"], (width, "img leak", im)
    blocks = rep.get("cases") or [{
        "shotImgs": rep["shotImgs"],
        "shots": rep["shots"],
        "copy": rep["copy"],
    }]
    assert len(blocks) >= 1, (width, "shot cases", len(blocks))
    for i, block in enumerate(blocks):
        shots = [x for x in block["shotImgs"] if x["on"]]
        assert len(shots) == 1, (width, i, "on-slide", block["shotImgs"])
        on = shots[0]
        assert on["inside"] and on["w"] > 80 and on["h"] > 60, (width, i, "case photo", on)
        for s in block["shotImgs"]:
            assert s["inside"], (width, i, "case leak", s)
            assert s["fit"] == "cover", (width, i, "shot fill", s)
        plate = block["shots"]
        copy = block["copy"]
        assert plate["w"] > 80 and plate["h"] > 60, (width, i, "plate", plate)
        assert 0.68 <= plate["h"] / plate["w"] <= 0.82, (width, i, "not 4/3", plate)
        if width >= 768:
            assert abs(plate["t"] - copy["t"]) <= 8, (width, i, "case not row", plate, copy)
            assert copy["h"] >= plate["h"] - 12, (width, i, "copy shorter than mock", plate, copy)
            assert plate["w"] < w * 0.72, (width, i, "shots ate row", plate)
        else:
            assert copy["t"] >= plate["b"] - 2, (width, i, "case not stacked", plate, copy)


def main() -> int:
    httpd, origin = _serve()
    dbg = _free_port()
    profile = tempfile.mkdtemp(prefix="layout-cdp-")
    exe = _browser()
    proc = subprocess.Popen(
        [
            str(exe),
            f"--remote-debugging-port={dbg}",
            f"--user-data-dir={profile}",
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--force-device-scale-factor=1",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    cdp = None
    try:
        _wait_json(f"http://127.0.0.1:{dbg}/json/version")
        tabs = _wait_json(f"http://127.0.0.1:{dbg}/json/list")
        page = next((t for t in tabs if t.get("type") == "page" and t.get("webSocketDebuggerUrl")), None)
        if not page:
            page = _wait_json(f"http://127.0.0.1:{dbg}/json/new?about:blank")
        cdp = Cdp(page["webSocketDebuggerUrl"])
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        cdp.call("Page.navigate", {"url": origin})
        for _ in range(50):
            if cdp.eval("document.readyState") == "complete":
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("page not complete")
        cdp.eval(
            "Promise.all([...document.images].map(i => i.complete ? 0 : new Promise(r => { i.onload = i.onerror = r })))",
            True,
        )
        screens = [(w, HEIGHT) for w in WIDTHS] + list(SCREENS)
        for width, height in screens:
            cdp.call(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": width,
                    "height": height,
                    "deviceScaleFactor": 1,
                    "mobile": width < 768,
                    "dontSetVisibleSize": False,
                },
            )
            cdp.eval("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))", True)
            rep = cdp.eval(PROBE)
            _check(rep, width)
        print(f"ok {len(screens)} screens")
        return 0
    finally:
        if cdp:
            cdp.close()
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
        httpd.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
