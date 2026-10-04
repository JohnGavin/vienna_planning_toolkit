"""A minimal Chrome DevTools Protocol driver (standard library only), for the editor's browser check (tools/check_editor.py).

Starts local headless Chrome with a throw-away profile under _scratch/, opens one page and lets a check evaluate JavaScript,
send real mouse events, change the viewport and colour scheme, and take screenshots, while recording every network request
and every console error or uncaught exception. Chrome listens on 127.0.0.1 only. Every wait has a deadline.

    with Browser() as b:
        b.open(path)                      # waits for the load event
        b.js("document.title")            # value of an expression (promises are awaited)
        b.mouse("mousePressed", x, y)     # a real input event (pointer events follow)
        png = b.screenshot([x, y, w, h])  # PNG bytes of that CSS-pixel rectangle of the viewport
        b.requests, b.errors              # URLs requested, console errors and exceptions
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request

CHROME = os.environ.get("VPT_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
SCRATCH = pathlib.Path(__file__).resolve().parent.parent / "_scratch"


class CDPError(RuntimeError):
    pass


class _WS:
    """Just enough of RFC 6455 for CDP: text frames, client masking, fragmented and 64-bit-length frames."""

    def __init__(self, url: str):
        assert url.startswith("ws://")
        hostport, path = url[5:].split("/", 1)
        host, port = hostport.split(":")
        self.s = socket.create_connection((host, int(port)), timeout=60)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.s.recv(4096)
            if not chunk:
                raise CDPError("websocket handshake failed")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise CDPError("websocket handshake refused")
        self.buf = head.split(b"\r\n\r\n", 1)[1]
        self.deadline = None

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            if self.deadline is not None:
                left = self.deadline - time.monotonic()
                if left <= 0:
                    raise CDPError("timed out waiting for Chrome")
                self.s.settimeout(left)
            try:
                chunk = self.s.recv(1 << 20)
            except socket.timeout as e:
                raise CDPError("timed out waiting for Chrome") from e
            if not chunk:
                raise CDPError("websocket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, text: str) -> None:
        data = text.encode()
        n = len(data)
        head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536
                                else bytes([0x80 | 127]) + struct.pack(">Q", n))
        mask = os.urandom(4)
        self.s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self, deadline: float | None = None) -> str:
        self.deadline = deadline
        parts = []
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(n)
            op = b0 & 0x0F
            if op == 0x8:
                raise CDPError("websocket closed by Chrome")
            if op in (0x9, 0xA):
                continue
            parts.append(payload)
            if b0 & 0x80:
                return b"".join(parts).decode()


class Browser:
    def __init__(self, flags: list[str] | None = None, size: tuple[int, int] = (1400, 1000), call_timeout: float = 30.0):
        self.flags = flags or []
        self.call_timeout = call_timeout
        self.size = size
        self.proc = None
        self.ws = None
        self.n = 0
        self.errors: list[str] = []
        self.requests: list[str] = []
        self.profile = None

    def __enter__(self):
        try:
            return self._start()
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _start(self):
        if not pathlib.Path(CHROME).exists():
            raise FileNotFoundError(CHROME)
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.profile = tempfile.mkdtemp(prefix="cdp_profile_", dir=SCRATCH)
        self.proc = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--disable-extensions",
                                      "--no-default-browser-check", "--hide-scrollbars", f"--window-size={self.size[0]},{self.size[1]}",
                                      "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", f"--user-data-dir={self.profile}",
                                      *self.flags, "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = pathlib.Path(self.profile) / "DevToolsActivePort"
        for _ in range(300):
            if port_file.exists() and port_file.read_text().strip():
                break
            time.sleep(0.1)
        else:
            raise CDPError("Chrome did not open its debugging port")
        port = port_file.read_text().split()[0]
        pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=30))
        page = next(p for p in pages if p.get("type") == "page")
        self.ws = _WS(page["webSocketDebuggerUrl"])
        for m in ("Page.enable", "Runtime.enable", "Network.enable", "Log.enable"):
            self.call(m)
        return self

    def __exit__(self, *exc):
        try:
            if self.ws:
                self.ws.s.close()
            if self.proc:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=10)
        finally:
            if self.profile:
                shutil.rmtree(self.profile, ignore_errors=True)

    def _event(self, msg: dict) -> None:
        m, p = msg.get("method"), msg.get("params") or {}
        if m == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails") or {}
            self.errors.append("exception: " + d.get("text", "") + " " + str((d.get("exception") or {}).get("description", ""))[:300])
        elif m == "Runtime.consoleAPICalled" and p.get("type") in ("error", "assert"):
            self.errors.append("console: " + " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args") or [])[:300])
        elif m == "Log.entryAdded" and (p.get("entry") or {}).get("level") == "error":
            self.errors.append("log: " + str(p["entry"].get("text", ""))[:300] + " " + str(p["entry"].get("url", ""))[:200])
        elif m == "Network.requestWillBeSent":
            self.requests.append((p.get("request") or {}).get("url", ""))

    def call(self, method: str, params: dict | None = None, wait_event: str | None = None, timeout: float | None = None) -> dict:
        """Send one CDP command and wait for its reply (and wait_event if given), at most timeout s (default call_timeout)."""
        deadline = time.monotonic() + (timeout or self.call_timeout)
        self.n += 1
        my = self.n
        self.ws.send(json.dumps({"id": my, "method": method, "params": params or {}}))
        result, seen = None, wait_event is None
        while result is None or not seen:
            msg = json.loads(self.ws.recv(deadline))
            if msg.get("id") == my:
                if "error" in msg:
                    raise CDPError(f"{method}: {msg['error']}")
                result = msg.get("result", {})
            else:
                if wait_event and msg.get("method") == wait_event:
                    seen = True
                self._event(msg)
        return result

    def open(self, url: str, settle: float = 1.0) -> None:
        self.errors, self.requests = [], []
        self.call("Page.navigate", {"url": url}, wait_event="Page.loadEventFired", timeout=60)
        time.sleep(settle)
        self.call("Runtime.evaluate", {"expression": "1"})          # collect events that arrived while settling

    def js(self, expr: str, timeout: float | None = None):
        r = self.call("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True, "userGesture": True}, timeout=timeout)
        if r.get("exceptionDetails"):
            d = r["exceptionDetails"]
            raise CDPError("JS: " + str((d.get("exception") or {}).get("description") or d.get("text"))[:400])
        return (r.get("result") or {}).get("value")

    def mouse(self, kind: str, x: float, y: float, buttons: int = 1, modifiers: int = 0) -> None:
        self.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left" if kind != "mouseMoved" or buttons else "none",
                                               "buttons": buttons, "clickCount": 1 if kind in ("mousePressed", "mouseReleased") else 0,
                                               "modifiers": modifiers})

    def drag(self, x0: float, y0: float, x1: float, y1: float, steps: int = 8) -> None:
        self.mouse("mouseMoved", x0, y0, buttons=0)
        self.mouse("mousePressed", x0, y0)
        for i in range(1, steps + 1):
            self.mouse("mouseMoved", x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)
        self.mouse("mouseReleased", x1, y1, buttons=0)

    def click(self, x: float, y: float) -> None:
        self.mouse("mouseMoved", x, y, buttons=0)
        self.mouse("mousePressed", x, y)
        self.mouse("mouseReleased", x, y, buttons=0)

    def viewport(self, width: int, height: int, mobile: bool = False) -> None:
        self.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": mobile})

    def colour_scheme(self, scheme: str) -> None:
        self.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]})

    def screenshot(self, rect: list[float]) -> bytes:
        x, y, w, h = rect
        sx, sy = self.js("[window.scrollX, window.scrollY]")
        r = self.call("Page.captureScreenshot", {"format": "png", "clip": {"x": x + sx, "y": y + sy, "width": max(1, w), "height": max(1, h), "scale": 1},
                                                 "captureBeyondViewport": False})
        return base64.b64decode(r["data"])

    def pixels(self, png: bytes, background: tuple[int, int, int], tol: int = 24) -> int:
        """Pixels of a PNG that differ from `background` by more than tol in any channel (decoded in the page's canvas)."""
        b64 = base64.b64encode(png).decode()
        r, g, b = background
        return self.js("new Promise(function (ok, bad) { var im = new Image(); im.onload = function () { var c = document.createElement('canvas');"
                       " c.width = im.width; c.height = im.height; var x = c.getContext('2d'); x.drawImage(im, 0, 0);"
                       " var d = x.getImageData(0, 0, c.width, c.height).data, n = 0;"
                       f" for (var i = 0; i < d.length; i += 4) if (Math.abs(d[i] - {r}) > {tol} || Math.abs(d[i+1] - {g}) > {tol} || Math.abs(d[i+2] - {b}) > {tol}) n++; ok(n); }};"
                       f" im.onerror = function () {{ bad('png decode'); }}; im.src = 'data:image/png;base64,{b64}'; }})")
