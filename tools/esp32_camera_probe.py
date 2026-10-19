#!/usr/bin/env python3
"""Probe and benchmark an ESP32(-S3) camera for use in soarm-ws.

Answers the questions the perception plan (docs/perception-tamp-integration-plan.md,
Stage 8) asks before the ESP32 becomes a second viewpoint: what resolutions it
really delivers, request latency and jitter, stream frame rate, image quality,
and whether ArUco markers / a chessboard are detectable at a given distance.

Three transports are supported:

* ``http``   — Espressif ``CameraWebServer`` example (``/capture``, ``/status``,
               ``/control``, MJPEG on ``:81/stream``). The usual firmware.
* ``stream`` — any MJPEG-over-HTTP URL (e.g. ``http://<ip>:81/stream``).
* ``uvc``    — the S3 flashed as a USB webcam (``usb_camera``/UVC example),
               opened through OpenCV ``VideoCapture(<index>)``.

Only needs ``numpy`` and ``opencv-python`` (``opencv-contrib`` not required).

Examples::

    python tools/esp32_camera_probe.py info  --host 192.168.1.42
    python tools/esp32_camera_probe.py bench --host 192.168.1.42 -n 50 --save runs/esp32
    python tools/esp32_camera_probe.py sweep --host 192.168.1.42 --framesizes 6,8,10,11,12,13
    python tools/esp32_camera_probe.py stream --url http://192.168.1.42:81/stream --duration 20
    python tools/esp32_camera_probe.py uvc --index 1 --duration 20
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import cv2
import numpy as np

# esp32-camera framesize_t names. The enum has shifted between esp32-camera
# releases, so these are labels only — the report always uses the resolution
# decoded from the returned JPEG.
FRAMESIZE_NAMES = {
    0: "96X96", 1: "QQVGA", 2: "128X128", 3: "QCIF", 4: "HQVGA", 5: "240X240",
    6: "QVGA", 7: "320X320", 8: "CIF", 9: "HVGA", 10: "VGA", 11: "SVGA",
    12: "XGA", 13: "HD", 14: "SXGA", 15: "UXGA",
}


# --------------------------------------------------------------------------- http


def _get(url: str, timeout: float) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def http_status(host: str, timeout: float) -> dict:
    return json.loads(_get(f"http://{host}/status", timeout))


def http_control(host: str, var: str, val: int, timeout: float) -> None:
    _get(f"http://{host}/control?var={var}&val={val}", timeout)


def http_capture(host: str, timeout: float) -> tuple[bytes, float]:
    """One still JPEG plus its round-trip time in seconds (host receipt clock)."""
    t0 = time.perf_counter()
    data = _get(f"http://{host}/capture?_={time.monotonic_ns()}", timeout)
    return data, time.perf_counter() - t0


def iter_mjpeg(url: str, timeout: float):
    """Yield (jpeg_bytes, host_receive_monotonic) from an MJPEG stream.

    Splits on JPEG SOI/EOI markers rather than multipart headers, which is
    robust to the slightly non-standard boundaries some firmwares emit.
    """
    with urllib.request.urlopen(url, timeout=timeout) as r:
        buf = b""
        while True:
            chunk = r.read(4096)
            if not chunk:
                return
            buf += chunk
            while True:
                start = buf.find(b"\xff\xd8")
                end = buf.find(b"\xff\xd9", start + 2) if start >= 0 else -1
                if start < 0 or end < 0:
                    if start > 0:
                        buf = buf[start:]
                    break
                yield buf[start:end + 2], time.monotonic()
                buf = buf[end + 2:]


# ------------------------------------------------------------------------ metrics


def _aruco_detector(dict_name: str):
    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dict_name))
    return cv2.aruco.ArucoDetector(d, cv2.aruco.DetectorParameters())


def frame_metrics(img: np.ndarray, aruco, chessboard: tuple[int, int] | None) -> dict:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    m = {
        "width": int(img.shape[1]),
        "height": int(img.shape[0]),
        # Variance of the Laplacian: higher = sharper. Compare between settings
        # on the same scene, not as an absolute number.
        "sharpness": float(cv2.Laplacian(gray, cv2.CV_64F).var()),
        "brightness": float(gray.mean()),
        "clipped_pct": float(((gray <= 2) | (gray >= 253)).mean() * 100),
    }
    if aruco is not None:
        corners, ids, _ = aruco.detectMarkers(gray)
        m["aruco_ids"] = [] if ids is None else sorted(int(i) for i in ids.ravel())
        # Smallest marker edge in pixels — the number that limits PnP accuracy.
        m["aruco_min_edge_px"] = (
            float(min(np.linalg.norm(c[0][0] - c[0][1]) for c in corners)) if corners else None
        )
    if chessboard is not None:
        ok, _ = cv2.findChessboardCorners(gray, chessboard, cv2.CALIB_CB_FAST_CHECK)
        m["chessboard"] = bool(ok)
    return m


def summarize(values: list[float]) -> dict | None:
    if not values:
        return None
    v = sorted(values)
    return {
        "n": len(v),
        "mean": statistics.fmean(v),
        "p50": v[len(v) // 2],
        "p95": v[min(len(v) - 1, int(round(0.95 * (len(v) - 1))))],
        "max": v[-1],
        "stdev": statistics.pstdev(v),
    }


def temporal_noise(frames: list[np.ndarray]) -> float | None:
    """Mean per-pixel std over a static scene (grey levels). Needs >=5 frames."""
    if len(frames) < 5 or len({f.shape for f in frames}) != 1:
        return None
    stack = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32) for f in frames])
    return float(stack.std(axis=0).mean())


def aggregate(per_frame: list[dict], frames: list[np.ndarray]) -> dict:
    out = {
        "resolutions": sorted({f"{m['width']}x{m['height']}" for m in per_frame}),
        "sharpness": summarize([m["sharpness"] for m in per_frame]),
        "brightness": summarize([m["brightness"] for m in per_frame]),
        "clipped_pct": summarize([m["clipped_pct"] for m in per_frame]),
        "temporal_noise": temporal_noise(frames),
    }
    if per_frame and "aruco_ids" in per_frame[0]:
        hits = [m for m in per_frame if m["aruco_ids"]]
        out["aruco_detect_rate"] = len(hits) / len(per_frame)
        out["aruco_ids_seen"] = sorted({i for m in hits for i in m["aruco_ids"]})
        out["aruco_min_edge_px"] = summarize(
            [m["aruco_min_edge_px"] for m in hits if m["aruco_min_edge_px"]]
        )
    if per_frame and "chessboard" in per_frame[0]:
        out["chessboard_detect_rate"] = sum(m["chessboard"] for m in per_frame) / len(per_frame)
    return out


# ----------------------------------------------------------------------- commands


def _decode(jpeg: bytes) -> np.ndarray | None:
    return cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)


def _save(save: Path | None, tag: str, i: int, jpeg: bytes) -> None:
    if save is not None and i < 5:
        save.mkdir(parents=True, exist_ok=True)
        (save / f"{tag}_{i:02d}.jpg").write_bytes(jpeg)


def bench_snapshots(host, n, timeout, aruco, chessboard, save, tag="capture",
                    progress=None) -> dict:
    """``progress(i, n)``, if given, is called before each capture."""
    latencies, sizes, per_frame, frames, errors = [], [], [], [], []
    for i in range(n):
        if progress is not None:
            progress(i, n)
        try:
            jpeg, dt = http_capture(host, timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            errors.append(repr(e))
            continue
        img = _decode(jpeg)
        if img is None:
            errors.append("jpeg decode failed")
            continue
        latencies.append(dt * 1000)
        sizes.append(len(jpeg) / 1024)
        per_frame.append(frame_metrics(img, aruco, chessboard))
        frames.append(img)
        _save(save, tag, i, jpeg)
    return {
        "mode": "http-snapshot",
        "requested": n,
        "ok": len(latencies),
        "errors": errors[:10],
        "error_count": len(errors),
        "latency_ms": summarize(latencies),
        "jpeg_kb": summarize(sizes),
        "effective_fps": (1000 / statistics.fmean(latencies)) if latencies else None,
        **aggregate(per_frame, frames),
    }


def bench_frames(frame_iter, duration, aruco, chessboard, save, mode) -> dict:
    """Shared stream/UVC benchmark: frame rate, inter-frame jitter, quality."""
    stamps, per_frame, frames, sizes = [], [], [], []
    t_end = time.monotonic() + duration
    for i, (img, t, nbytes) in enumerate(frame_iter):
        stamps.append(t)
        if nbytes:
            sizes.append(nbytes / 1024)
        # Metrics on every 5th frame keep the analysis from throttling the stream.
        if i % 5 == 0:
            per_frame.append(frame_metrics(img, aruco, chessboard))
            if len(frames) < 30:
                frames.append(img)
            if save is not None and len(frames) <= 5:
                save.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(save / f"{mode}_{len(frames) - 1:02d}.jpg"), img)
        if t >= t_end:
            break
    gaps = [(b - a) * 1000 for a, b in zip(stamps, stamps[1:])]
    span = stamps[-1] - stamps[0] if len(stamps) > 1 else 0
    return {
        "mode": mode,
        "frames": len(stamps),
        "fps": (len(stamps) - 1) / span if span else None,
        "interframe_ms": summarize(gaps),
        "stalls_over_250ms": sum(g > 250 for g in gaps),
        "jpeg_kb": summarize(sizes),
        **aggregate(per_frame, frames),
    }


def _mjpeg_frames(url, timeout):
    for jpeg, t in iter_mjpeg(url, timeout):
        img = _decode(jpeg)
        if img is not None:
            yield img, t, len(jpeg)


def _uvc_frames(index, width, height):
    cap = cv2.VideoCapture(index)
    if width:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    if height:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    if not cap.isOpened():
        raise SystemExit(f"cannot open VideoCapture({index})")
    try:
        while True:
            ok, img = cap.read()
            if not ok:
                return
            yield img, time.monotonic(), 0
    finally:
        cap.release()


def cmd_info(a) -> dict:
    st = http_status(a.host, a.timeout)
    fs = st.get("framesize")
    return {"status": st, "framesize_name": FRAMESIZE_NAMES.get(fs, "?")}


def sweep(host, framesizes, n, timeout, settle, aruco, chessboard, save,
          progress=None) -> list[dict]:
    """Bench each framesize in turn, then restore the camera's original one.

    ``progress(step, total)`` counts captures across the whole sweep.
    """
    original = http_status(host, timeout).get("framesize")
    results = []
    try:
        for k, fs in enumerate(framesizes):
            try:
                http_control(host, "framesize", fs, timeout)
            except urllib.error.URLError as e:
                results.append({"framesize": fs, "error": repr(e)})
                continue
            time.sleep(settle)
            # Discard frames buffered at the previous size.
            for _ in range(2):
                try:
                    http_capture(host, timeout)
                except (urllib.error.URLError, OSError):
                    pass
            step = None if progress is None else (
                lambda i, _n, k=k: progress(k * n + i, len(framesizes) * n))
            r = bench_snapshots(host, n, timeout, aruco, chessboard, save,
                                tag=f"fs{fs}", progress=step)
            results.append({"framesize": fs, "name": FRAMESIZE_NAMES.get(fs, "?"), **r})
    finally:
        if original is not None:
            http_control(host, "framesize", original, timeout)
    return results


def cmd_sweep(a, aruco, chessboard) -> dict:
    framesizes = [int(x) for x in a.framesizes.split(",")]
    return {"sweep": sweep(a.host, framesizes, a.n, a.timeout, a.settle,
                           aruco, chessboard, a.save)}


def print_sweep_table(results: list[dict]) -> None:
    hdr = f"{'fs':>3} {'name':8} {'res':>10} {'ok':>5} {'p50ms':>7} {'p95ms':>7} " \
          f"{'fps':>5} {'KB':>6} {'sharp':>7} {'aruco':>6}"
    print(hdr, file=sys.stderr)
    for r in results:
        if "error" in r:
            print(f"{r['framesize']:>3} error: {r['error']}", file=sys.stderr)
            continue
        lat, kb, sh = r["latency_ms"] or {}, r["jpeg_kb"] or {}, r["sharpness"] or {}
        ar = r.get("aruco_detect_rate")
        print(f"{r['framesize']:>3} {r['name']:8} {','.join(r['resolutions']):>10} "
              f"{r['ok']:>2}/{r['requested']:<2} {lat.get('p50', 0):7.0f} {lat.get('p95', 0):7.0f} "
              f"{r['effective_fps'] or 0:5.1f} {kb.get('mean', 0):6.1f} {sh.get('mean', 0):7.0f} "
              f"{'' if ar is None else f'{ar:.0%}':>6}", file=sys.stderr)


def main(argv=None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--timeout", type=float, default=5.0, help="per-request timeout [s]")
    common.add_argument("--aruco-dict", default="DICT_4X4_50",
                   help="ArUco dictionary to detect ('none' to skip); must match the printed marker")
    common.add_argument("--chessboard", default=None,
                   help="inner-corner grid to detect, e.g. 9x6 (matches camera_calibration)")
    common.add_argument("--save", type=Path, default=None, help="directory for sample frames")
    common.add_argument("--json", type=Path, default=None, help="write the full report here")
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("info", parents=[common], help="dump CameraWebServer /status (sensor settings)")
    s.add_argument("--host", required=True)

    s = sub.add_parser("bench", parents=[common], help="N still captures: latency, size, quality")
    s.add_argument("--host", required=True)
    s.add_argument("-n", type=int, default=30)

    s = sub.add_parser("sweep", parents=[common], help="bench at several framesizes, then restore")
    s.add_argument("--host", required=True)
    s.add_argument("-n", type=int, default=15)
    s.add_argument("--framesizes", default="6,8,10,11,12,13")
    s.add_argument("--settle", type=float, default=1.0, help="wait after a size change [s]")

    s = sub.add_parser("stream", parents=[common], help="MJPEG stream: fps, jitter, stalls, quality")
    s.add_argument("--url", required=True, help="e.g. http://<ip>:81/stream")
    s.add_argument("--duration", type=float, default=15.0)

    s = sub.add_parser("uvc", parents=[common], help="S3 as USB webcam via OpenCV VideoCapture")
    s.add_argument("--index", type=int, default=0)
    s.add_argument("--width", type=int, default=0)
    s.add_argument("--height", type=int, default=0)
    s.add_argument("--duration", type=float, default=15.0)

    a = p.parse_args(argv)
    aruco = None if a.aruco_dict.lower() == "none" else _aruco_detector(a.aruco_dict)
    chessboard = tuple(int(x) for x in a.chessboard.split("x")) if a.chessboard else None

    if a.cmd == "info":
        report = cmd_info(a)
    elif a.cmd == "bench":
        report = bench_snapshots(a.host, a.n, a.timeout, aruco, chessboard, a.save)
    elif a.cmd == "sweep":
        report = cmd_sweep(a, aruco, chessboard)
        print_sweep_table(report["sweep"])
    elif a.cmd == "stream":
        report = bench_frames(_mjpeg_frames(a.url, a.timeout), a.duration,
                              aruco, chessboard, a.save, "mjpeg-stream")
    else:
        report = bench_frames(_uvc_frames(a.index, a.width, a.height), a.duration,
                              aruco, chessboard, a.save, "uvc")

    report["meta"] = {
        "cmd": a.cmd,
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "aruco_dict": a.aruco_dict,
        "opencv": cv2.__version__,
    }
    text = json.dumps(report, indent=2, default=float)
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
