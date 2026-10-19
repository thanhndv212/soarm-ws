#!/usr/bin/env python3
"""Browser GUI for exploring and benchmarking an ESP32(-S3) camera.

Runs a small local web server that is the *single owner* of the camera (the
perception plan's rule): it reads the ESP32 MJPEG stream (or a UVC webcam),
reconnects on failure, measures frame rate / jitter / stalls / image quality
live, draws ArUco and chessboard detections, exposes every CameraWebServer
sensor control, and runs the snapshot benchmark and framesize sweep from
``esp32_camera_probe`` while pausing the stream so they don't fight over it.

    python tools/esp32_camera_gui.py --host 192.168.1.42        # CameraWebServer
    python tools/esp32_camera_gui.py --uvc 1                    # S3 as USB webcam
    python tools/esp32_camera_mock.py & python tools/esp32_camera_gui.py --host 127.0.0.1:8080

then open http://127.0.0.1:8000. Needs only numpy + opencv-python.
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
import threading
import time
import traceback
import urllib.error
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import esp32_camera_probe as probe  # noqa: E402

HTML = Path(__file__).with_name("esp32_camera_gui.html")
ARUCO_DICTS = ["DICT_4X4_50", "DICT_5X5_100", "DICT_6X6_250", "DICT_7X7_1000", "DICT_ARUCO_ORIGINAL"]
STALL_MS = 250


def stream_url_for(host: str) -> str:
    """CameraWebServer serves the stream on the control port + 1 (80 -> 81)."""
    name, _, port = host.partition(":")
    return f"http://{name}:{int(port or 80) + 1}/stream"


class Camera:
    """Owns the camera: reads frames, keeps live stats, renders the overlay."""

    def __init__(self, host: str | None, stream_url: str | None, uvc: int | None,
                 timeout: float, save_dir: Path):
        self.host, self.uvc, self.timeout = host, uvc, timeout
        self.stream_url = stream_url or (stream_url_for(host) if host else None)
        self.save_dir = save_dir
        self.lock = threading.Lock()
        self.new_frame = threading.Condition(self.lock)
        self.annotated: bytes | None = None
        self.raw: bytes | None = None
        self.seq = 0
        self.conn = "connecting"
        self.last_error = ""
        self.reconnects = 0
        self.paused = threading.Event()
        self.idle = threading.Event()
        self.overlay = {"aruco": True, "aruco_dict": "DICT_4X4_50", "chessboard": "9x6",
                        "grid": False}
        self._detector = probe._aruco_detector("DICT_4X4_50")
        self.stamps: collections.deque[float] = collections.deque(maxlen=300)
        self.sizes: collections.deque[float] = collections.deque(maxlen=100)
        self.stall_times: collections.deque[float] = collections.deque(maxlen=1000)
        self.noise_buf: collections.deque[np.ndarray] = collections.deque(maxlen=10)
        self.aruco_hist: collections.deque[bool] = collections.deque(maxlen=60)
        self.metrics: dict = {}
        self.detections: dict = {"aruco": [], "chessboard": None}
        self.history: collections.deque[dict] = collections.deque(maxlen=120)
        self.started = time.monotonic()
        self.frames_total = 0

    # --- frame sources -------------------------------------------------------

    def _frames(self):
        if self.uvc is not None:
            yield from probe._uvc_frames(self.uvc, 0, 0)
        else:
            yield from probe._mjpeg_frames(self.stream_url, self.timeout)

    def run(self):
        backoff = 0.5
        while True:
            if self.paused.is_set():
                if not self.idle.is_set():
                    # A benchmark pause is not a stall: restart interval stats
                    # and break the history line instead of bridging the gap.
                    self.stamps.clear()
                    self.history.append({"t": time.monotonic(), "fps": None,
                                         "interframe_p95": None, "sharpness": None})
                self.idle.set()
                self.conn = "paused"
                time.sleep(0.1)
                continue
            self.idle.clear()
            try:
                self.conn = "connecting"
                for img, t, nbytes in self._frames():
                    if self.conn != "streaming":
                        self.conn, backoff = "streaming", 0.5
                    self._on_frame(img, t, nbytes)
                    if self.paused.is_set():
                        break
                else:
                    raise ConnectionError("stream ended")
            except Exception as e:  # noqa: BLE001 — any source failure means reconnect
                if self.paused.is_set():
                    continue
                self.last_error = f"{type(e).__name__}: {e}"
                self.conn = "reconnecting"
                self.reconnects += 1
                time.sleep(backoff)
                backoff = min(backoff * 2, 8)

    # --- per-frame work ------------------------------------------------------

    def _on_frame(self, img: np.ndarray, t: float, nbytes: int):
        if self.stamps and (t - self.stamps[-1]) * 1000 > STALL_MS:
            self.stall_times.append(t)
        self.stamps.append(t)
        if nbytes:
            self.sizes.append(nbytes / 1024)
        self.frames_total += 1
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Detection and quality metrics every 2nd frame keep up with HD streams.
        if self.frames_total % 2 == 0 or not self.metrics:
            m = probe.frame_metrics(img, None, None)
            small = cv2.resize(gray, (160, max(1, 160 * gray.shape[0] // gray.shape[1])))
            if self.noise_buf and self.noise_buf[0].shape != small.shape:
                self.noise_buf.clear()
            self.noise_buf.append(small.astype(np.float32))
            det = {"aruco": [], "chessboard": None}
            if self.overlay["aruco"]:
                corners, ids, _ = self._detector.detectMarkers(gray)
                if ids is not None:
                    det["aruco"] = [(int(i), c[0].tolist()) for i, c in zip(ids.ravel(), corners)]
                self.aruco_hist.append(ids is not None)
            pattern = self._pattern()
            if pattern:
                ok, pts = cv2.findChessboardCorners(gray, pattern, cv2.CALIB_CB_FAST_CHECK)
                det["chessboard"] = pts if ok else False
            self.detections = det
            self.metrics = m

        out = self._draw(img.copy())
        jpeg = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
        raw = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()
        with self.new_frame:
            self.annotated, self.raw = jpeg, raw
            self.seq += 1
            self.new_frame.notify_all()
        if not self.history or t - self.history[-1]["t"] >= 1.0:
            s = self.live_stats()
            self.history.append({"t": t, "fps": s["fps"], "interframe_p95": s["interframe_ms"]["p95"]
                                 if s["interframe_ms"] else None, "sharpness": s["sharpness"]})

    def _pattern(self):
        try:
            c, r = self.overlay["chessboard"].lower().split("x")
            return int(c), int(r)
        except (AttributeError, ValueError):
            return None

    def _draw(self, img):
        h, w = img.shape[:2]
        th = max(1, w // 400)
        if self.overlay["grid"]:
            for k in (1, 2):
                cv2.line(img, (w * k // 3, 0), (w * k // 3, h), (255, 255, 255), 1, cv2.LINE_AA)
                cv2.line(img, (0, h * k // 3), (w, h * k // 3), (255, 255, 255), 1, cv2.LINE_AA)
        cb = self.detections.get("chessboard")
        if cb is not None and cb is not False:
            cv2.drawChessboardCorners(img, self._pattern(), cb, True)
        for mid, corners in self.detections.get("aruco", []):
            pts = np.int32(corners)
            cv2.polylines(img, [pts], True, (0, 230, 0), 2 * th, cv2.LINE_AA)
            cv2.circle(img, tuple(pts[0]), 4 * th, (0, 0, 255), -1, cv2.LINE_AA)
            edge = float(np.linalg.norm(pts[0] - pts[1]))
            label = f"id {mid}  {edge:.0f}px"
            org = (int(pts[:, 0].min()), max(14, int(pts[:, 1].min()) - 8))
            cv2.putText(img, label, org, cv2.FONT_HERSHEY_SIMPLEX, 0.5 * th, (0, 0, 0), 4 * th, cv2.LINE_AA)
            cv2.putText(img, label, org, cv2.FONT_HERSHEY_SIMPLEX, 0.5 * th, (0, 255, 0), th, cv2.LINE_AA)
        return img

    # --- reporting -----------------------------------------------------------

    def live_stats(self) -> dict:
        stamps = list(self.stamps)
        now = time.monotonic()
        recent = [s for s in stamps if now - s <= 5]
        tail = stamps[-60:]
        gaps = [(b - a) * 1000 for a, b in zip(tail, tail[1:])]
        fps = (len(recent) - 1) / (recent[-1] - recent[0]) if len(recent) > 2 else None
        noise = None
        if len(self.noise_buf) >= 5:
            noise = float(np.stack(self.noise_buf).std(axis=0).mean())
        m = self.metrics
        aruco = self.detections.get("aruco", [])
        return {
            "fps": fps,
            "interframe_ms": probe.summarize(gaps),
            "frame_age_ms": (now - stamps[-1]) * 1000 if stamps else None,
            "stalls_total": len(self.stall_times),
            "stalls_last_min": sum(now - s <= 60 for s in self.stall_times),
            "jpeg_kb": statistics.fmean(self.sizes) if self.sizes else None,
            "resolution": f"{m['width']}x{m['height']}" if m else None,
            "sharpness": m.get("sharpness"),
            "brightness": m.get("brightness"),
            "clipped_pct": m.get("clipped_pct"),
            "temporal_noise": noise,
            "aruco_ids": [i for i, _ in aruco],
            "aruco_min_edge_px": min((float(np.linalg.norm(np.subtract(c[0], c[1]))) for _, c in aruco),
                                     default=None),
            "aruco_rate": (sum(self.aruco_hist) / len(self.aruco_hist)) if self.aruco_hist else None,
            "chessboard": (None if self.detections.get("chessboard") is None
                           else self.detections["chessboard"] is not False),
            "frames_total": self.frames_total,
            "uptime_s": now - self.started,
        }

    def set_overlay(self, cfg: dict):
        if "aruco_dict" in cfg and cfg["aruco_dict"] in ARUCO_DICTS:
            self._detector = probe._aruco_detector(cfg["aruco_dict"])
            self.aruco_hist.clear()
        for k in ("aruco", "grid"):
            if k in cfg:
                self.overlay[k] = bool(cfg[k])
        for k in ("aruco_dict", "chessboard"):
            if k in cfg:
                self.overlay[k] = cfg[k]

    def snapshot(self) -> str:
        with self.lock:
            raw, ann = self.raw, self.annotated
        if raw is None:
            raise RuntimeError("no frame yet")
        self.save_dir.mkdir(parents=True, exist_ok=True)
        stem = time.strftime("snap_%Y%m%d_%H%M%S")
        (self.save_dir / f"{stem}.jpg").write_bytes(raw)
        (self.save_dir / f"{stem}_overlay.jpg").write_bytes(ann)
        return str(self.save_dir / f"{stem}.jpg")


class Jobs:
    """Runs one benchmark at a time with the live stream paused."""

    def __init__(self, cam: Camera):
        self.cam = cam
        self.state = {"running": False, "kind": None, "progress": 0.0, "result": None,
                      "error": None, "finished_utc": None}
        self.lock = threading.Lock()

    def start(self, kind: str, n: int, framesizes: list[int]) -> None:
        with self.lock:
            if self.state["running"]:
                raise RuntimeError("a benchmark is already running")
            self.state.update(running=True, kind=kind, progress=0.0, error=None)
        threading.Thread(target=self._run, args=(kind, n, framesizes), daemon=True).start()

    def _progress(self, i, n):
        self.state["progress"] = i / max(n, 1)

    def _run(self, kind, n, framesizes):
        cam = self.cam
        cam.paused.set()
        cam.idle.wait(timeout=cam.timeout + 2)
        try:
            pattern = cam._pattern()
            aruco = probe._aruco_detector(cam.overlay["aruco_dict"]) if cam.overlay["aruco"] else None
            save = cam.save_dir / time.strftime("bench_%Y%m%d_%H%M%S")
            if kind == "bench":
                result = probe.bench_snapshots(cam.host, n, cam.timeout, aruco, pattern, save,
                                               progress=self._progress)
            else:
                result = {"sweep": probe.sweep(cam.host, framesizes, n, cam.timeout, 1.0, aruco,
                                               pattern, save, progress=self._progress)}
            result["meta"] = {"kind": kind, "host": cam.host, "n": n, "aruco_dict": cam.overlay["aruco_dict"],
                              "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                              "opencv": cv2.__version__}
            save.mkdir(parents=True, exist_ok=True)
            (save / "report.json").write_text(json.dumps(result, indent=2, default=float))
            result["meta"]["report"] = str(save / "report.json")
            self.state.update(result=result, progress=1.0)
        except Exception as e:  # noqa: BLE001 — surfaced to the GUI
            self.state["error"] = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        finally:
            self.state.update(running=False, finished_utc=time.strftime("%H:%M:%S"))
            cam.paused.clear()


def make_handler(cam: Camera, jobs: Jobs, args):
    status_cache = {"status": None, "t": 0.0, "error": None}

    def camera_status(force=False):
        if cam.host is None:
            return None
        if force or time.monotonic() - status_cache["t"] > 2:
            try:
                status_cache.update(status=probe.http_status(cam.host, cam.timeout), error=None)
            except (urllib.error.URLError, OSError, ValueError) as e:
                status_cache["error"] = repr(e)
            status_cache["t"] = time.monotonic()
        return status_cache["status"]

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj, default=float).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                body = HTML.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path.startswith("/video"):
                self._video()
            elif self.path.startswith("/api/state"):
                self._json({
                    "source": {"kind": "uvc" if cam.uvc is not None else "http", "host": cam.host,
                               "stream_url": cam.stream_url, "uvc": cam.uvc},
                    "conn": cam.conn, "last_error": cam.last_error, "reconnects": cam.reconnects,
                    "live": cam.live_stats(), "history": list(cam.history), "overlay": cam.overlay,
                    "aruco_dicts": ARUCO_DICTS, "framesize_names": probe.FRAMESIZE_NAMES,
                    "camera_status": camera_status(), "camera_status_error": status_cache["error"],
                    "job": jobs.state, "save_dir": str(cam.save_dir),
                })
            else:
                self.send_error(404)

        def do_POST(self):
            try:
                body = self._body()
                if self.path == "/api/control":
                    if cam.host is None:
                        raise RuntimeError("sensor controls need a CameraWebServer host")
                    probe.http_control(cam.host, str(body["var"]), int(body["val"]), cam.timeout)
                    self._json({"ok": True, "status": camera_status(force=True)})
                elif self.path == "/api/overlay":
                    cam.set_overlay(body)
                    self._json({"ok": True, "overlay": cam.overlay})
                elif self.path == "/api/job":
                    if cam.host is None:
                        raise RuntimeError("snapshot benchmarks need a CameraWebServer host")
                    jobs.start(body.get("kind", "bench"), int(body.get("n", 30)),
                               [int(x) for x in body.get("framesizes", [6, 8, 10, 11, 12, 13])])
                    self._json({"ok": True})
                elif self.path == "/api/snapshot":
                    self._json({"ok": True, "path": cam.snapshot()})
                else:
                    self.send_error(404)
            except Exception as e:  # noqa: BLE001 — report to the GUI
                self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 400)

        def _video(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last = -1
            try:
                while True:
                    with cam.new_frame:
                        cam.new_frame.wait_for(lambda: cam.seq != last, timeout=1.0)
                        if cam.seq == last or cam.annotated is None:
                            continue
                        last, jpeg = cam.seq, cam.annotated
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n"
                                     % len(jpeg) + jpeg + b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                return

    return Handler


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--host", help="CameraWebServer address, e.g. 192.168.1.42 or 127.0.0.1:8080")
    src.add_argument("--uvc", type=int, help="OpenCV VideoCapture index (S3 flashed as USB webcam)")
    p.add_argument("--stream-url", help="override the MJPEG URL (default: http://HOST:PORT+1/stream)")
    p.add_argument("--listen", default="127.0.0.1:8000", help="GUI address")
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("--save-dir", type=Path, default=Path("runs/esp32_gui"))
    p.add_argument("--open", action="store_true", help="open the GUI in the default browser")
    a = p.parse_args(argv)

    cam = Camera(a.host, a.stream_url, a.uvc, a.timeout, a.save_dir)
    jobs = Jobs(cam)
    threading.Thread(target=cam.run, daemon=True).start()
    bind, _, port = a.listen.partition(":")
    srv = ThreadingHTTPServer((bind, int(port or 8000)), make_handler(cam, jobs, a))
    srv.daemon_threads = True
    url = f"http://{bind}:{port or 8000}"
    print(f"ESP32 camera GUI on {url}  (source: {cam.stream_url or f'uvc {a.uvc}'})")
    if a.open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
