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

    # live-stream fps / stalls / glass-to-host lag per framesize, no manual switching:
    python tools/esp32_camera_probe.py clock-page --out runs/esp32/clock.html   # open full-screen
    python tools/esp32_camera_probe.py stream-sweep --host 192.168.1.42 --clock --duration 10
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


def stream_url_for(host: str) -> str:
    """CameraWebServer serves the stream on the control port + 1 (80 -> 81)."""
    name, _, port = host.partition(":")
    return f"http://{name}:{int(port or 80) + 1}/stream"


def clock_ids(dict_name: str) -> int:
    """How many IDs the lag clock cycles through: the dictionary size, capped at 50."""
    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dict_name))
    return min(50, d.bytesList.shape[0])


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
            # read1, not read: read(n) blocks until n bytes arrive, which holds each
            # frame's tail back until the next frame starts and skews every timestamp.
            chunk = r.read1(65536)
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


# --------------------------------------------------------------- stream + lag


def clock_page_html(dict_name: str = "DICT_4X4_50", period_ms: int = 100, n_ids: int = 50) -> str:
    """A page that shows marker ``floor(now / period) % n_ids``, from the host's clock.

    Open it on a screen driven by the machine that runs the benchmark and point
    the camera at it: the marker ID in each received frame then says when that
    frame's light left the screen, so receipt time minus that is glass-to-host lag.
    """
    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dict_name))
    side = d.markerSize + 2  # one black border cell each side
    bits = [(cv2.aruco.generateImageMarker(d, i, side) > 127).astype(int).ravel().tolist()
            for i in range(n_ids)]
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Camera lag clock</title>
<style>html,body{{margin:0;height:100%;background:#fff;color:#000;font:14px system-ui}}
body{{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px}}
canvas{{width:min(70vmin,560px);height:min(70vmin,560px);image-rendering:pixelated}}</style></head>
<body><canvas id="c" width="{side + 2}" height="{side + 2}"></canvas>
<div id="t">{dict_name}, one ID per {period_ms} ms, IDs 0-{n_ids - 1}. Keep only this marker in view.</div>
<script>
const BITS={json.dumps(bits)}, SIDE={side}, PERIOD={period_ms}, N={n_ids};
const ctx=document.getElementById('c').getContext('2d'); let shown=-1;
function draw(){{
  const id=Math.floor(Date.now()/PERIOD)%N;
  if(id!==shown){{
    ctx.fillStyle='#fff'; ctx.fillRect(0,0,SIDE+2,SIDE+2); ctx.fillStyle='#000';
    BITS[id].forEach((b,k)=>{{ if(!b) ctx.fillRect(1+k%SIDE,1+Math.floor(k/SIDE),1,1); }});
    shown=id;
  }}
  requestAnimationFrame(draw);
}}
draw();
</script></body></html>
"""


def clock_lag_ms(t_wall: float, marker_id: int, period_s: float, n_ids: int) -> float:
    """Lag of a frame that shows clock marker ``marker_id``, received at ``t_wall``.

    The screen showed that ID during the most recent slot ``s <= now`` with
    ``s % n_ids == marker_id``. The camera sampled somewhere inside the slot, so
    the slot midpoint is the estimate; each sample is quantised to +-period/2,
    the median over many frames is not. Includes the screen's own display delay.
    """
    now_slot = int(t_wall // period_s)
    slot = now_slot - (now_slot - marker_id) % n_ids
    return (t_wall - (slot + 0.5) * period_s) * 1000


def bench_stream(url, duration, timeout, aruco, chessboard, save, tag="stream",
                 warmup=1.0, clock: dict | None = None) -> dict:
    """Record the raw MJPEG stream, *then* analyse it.

    Reading is not slowed by decoding or detection, so fps and inter-frame gaps
    are what the camera and network deliver. ``clock`` = {"detector", "period_ms",
    "n_ids"} enables glass-to-host lag from a ``clock_page_html`` screen in view.
    """
    wall_offset = time.time() - time.monotonic()
    rec, errors, t0 = [], [], None
    try:
        for jpeg, t in iter_mjpeg(url, timeout):
            t0 = t if t0 is None else t0
            if t - t0 < warmup:  # frames queued before/around the connect
                continue
            rec.append((jpeg, t))
            if t - t0 >= warmup + duration:
                break
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        errors.append(repr(e))

    stamps = [t for _, t in rec]
    gaps = [(b - a) * 1000 for a, b in zip(stamps, stamps[1:])]
    span = stamps[-1] - stamps[0] if len(stamps) > 1 else 0
    per_frame, frames, decode_ms, lags, clock_ids_seen = [], [], [], [], []
    for i, (jpeg, t) in enumerate(rec):
        d0 = time.perf_counter()
        img = _decode(jpeg)
        decode_ms.append((time.perf_counter() - d0) * 1000)
        if img is None:
            errors.append("jpeg decode failed")
            continue
        if clock is not None:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            _, ids, _ = clock["detector"].detectMarkers(gray)
            if ids is not None and len(ids) == 1:
                clock_ids_seen.append(int(ids[0][0]))
                lags.append(clock_lag_ms(t + wall_offset, int(ids[0][0]),
                                         clock["period_ms"] / 1000, clock["n_ids"]))
        if i % 5 == 0:
            per_frame.append(frame_metrics(img, aruco, chessboard))
            if len(frames) < 30:
                frames.append(img)
        _save(save, tag, i, jpeg)
    out = {
        "mode": "mjpeg-stream",
        "duration_s": span,
        "frames": len(rec),
        "fps": (len(rec) - 1) / span if span else None,
        "interframe_ms": summarize(gaps),
        "stalls_over_250ms": sum(g > 250 for g in gaps),
        "jpeg_kb": summarize([len(j) / 1024 for j, _ in rec]),
        "host_decode_ms": summarize(decode_ms),
        "errors": errors[:10],
        "error_count": len(errors),
        **aggregate(per_frame, frames),
    }
    if clock is not None:
        out["clock_detect_rate"] = len(clock_ids_seen) / len(rec) if rec else 0.0
        # A printed or stuck marker also decodes as one ID; only a running clock
        # cycles through many. Without that, the "lag" would be meaningless.
        expected = min(clock["n_ids"], span * 1000 / clock["period_ms"], len(clock_ids_seen))
        out["clock_ids_distinct"] = len(set(clock_ids_seen))
        out["clock_ok"] = bool(clock_ids_seen) and len(set(clock_ids_seen)) >= max(3, 0.3 * expected)
        out["lag_ms"] = summarize(lags) if out["clock_ok"] else None
    return out


def stream_sweep(host, stream_url, framesizes, duration, timeout, settle, aruco, chessboard,
                 save, clock=None, progress=None) -> list[dict]:
    """``bench_stream`` at each framesize, then restore the original one.

    ``progress(step, total)`` counts framesizes.
    """
    original = http_status(host, timeout).get("framesize")
    results = []
    try:
        for k, fs in enumerate(framesizes):
            if progress is not None:
                progress(k, len(framesizes))
            try:
                http_control(host, "framesize", fs, timeout)
            except urllib.error.URLError as e:
                results.append({"framesize": fs, "error": repr(e)})
                continue
            time.sleep(settle)
            r = bench_stream(stream_url, duration, timeout, aruco, chessboard, save,
                             tag=f"stream_fs{fs}", clock=clock)
            results.append({"framesize": fs, "name": FRAMESIZE_NAMES.get(fs, "?"), **r})
    finally:
        if original is not None:
            http_control(host, "framesize", original, timeout)
    return results


def print_stream_sweep_table(results: list[dict]) -> None:
    hdr = f"{'fs':>3} {'name':8} {'res':>10} {'fps':>5} {'gap50':>6} {'gap95':>6} {'stall':>5} " \
          f"{'KB':>6} {'lag50':>6} {'lag95':>6} {'clock':>6} {'dec':>5}"
    print(hdr, file=sys.stderr)
    for r in results:
        if "error" in r:
            print(f"{r['framesize']:>3} error: {r['error']}", file=sys.stderr)
            continue
        g, kb, lag, dec = (r.get(k) or {} for k in ("interframe_ms", "jpeg_kb", "lag_ms",
                                                     "host_decode_ms"))
        cr = r.get("clock_detect_rate")
        f = lambda d, k: f"{d[k]:6.0f}" if k in d else f"{'-':>6}"  # noqa: E731
        print(f"{r['framesize']:>3} {r['name']:8} {','.join(r['resolutions']):>10} "
              f"{r['fps'] or 0:5.1f} {f(g, 'p50')} {f(g, 'p95')} {r['stalls_over_250ms']:>5} "
              f"{kb.get('mean', 0):6.1f} {f(lag, 'p50')} {f(lag, 'p95')} "
              f"{'' if cr is None else f'{cr:.0%}' + ('' if r.get('clock_ok') else '!'):>6} "
              f"{dec.get('p50', 0):5.1f}", file=sys.stderr)
    if any(r.get("clock_ok") is False for r in results):
        print("! a marker was seen but its ID never cycled: not the lag clock, so no lag",
              file=sys.stderr)


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

    s = sub.add_parser("stream-sweep", parents=[common],
                       help="live stream at several framesizes: fps, gaps, stalls, glass-to-host lag")
    s.add_argument("--host", required=True)
    s.add_argument("--stream-url", default=None, help="default: http://HOST:PORT+1/stream")
    s.add_argument("--framesizes", default="6,8,10,11,12,13")
    s.add_argument("--duration", type=float, default=10.0, help="seconds per framesize")
    s.add_argument("--settle", type=float, default=1.0, help="wait after a size change [s]")
    s.add_argument("--clock", action="store_true",
                   help="measure lag from a `clock-page` screen in view (uses --aruco-dict)")
    s.add_argument("--clock-period-ms", type=int, default=100)

    s = sub.add_parser("clock-page", parents=[common],
                       help="write the lag-clock page (open it on this machine's screen)")
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--clock-period-ms", type=int, default=100)

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
    elif a.cmd == "clock-page":
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(clock_page_html(a.aruco_dict, a.clock_period_ms, clock_ids(a.aruco_dict)))
        print(f"wrote {a.out}; open it full-screen on this machine", file=sys.stderr)
        return 0
    elif a.cmd == "stream-sweep":
        clock = None
        if a.clock:
            clock = {"detector": _aruco_detector(a.aruco_dict), "period_ms": a.clock_period_ms,
                     "n_ids": clock_ids(a.aruco_dict)}
        url = a.stream_url or stream_url_for(a.host)
        report = {"stream_sweep": stream_sweep(
            a.host, url, [int(x) for x in a.framesizes.split(",")], a.duration, a.timeout,
            a.settle, aruco, chessboard, a.save, clock=clock)}
        if clock:
            report["clock"] = {"period_ms": a.clock_period_ms, "n_ids": clock["n_ids"]}
        print_stream_sweep_table(report["stream_sweep"])
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
