# ESP32-S3 camera evaluation

Status: protocol and tooling. No hardware results yet. Record them in the table at the bottom.

The [perception plan](perception-tamp-integration-plan.md) (Stage 8) and the
[roadmap](soarm-development-roadmap.md) give the ESP32 a narrow first role: a **second,
auxiliary view** for grip and placement verification and coarse object presence. It is
*not* the precision camera for `T_base_object`. That job stays with the fixed USB webcam.
This evaluation decides whether the board can fill the auxiliary role, and whether it could
do more.

Tool: [`tools/esp32_camera_probe.py`](../tools/esp32_camera_probe.py). It needs only
`numpy` and `opencv-python`, and runs on the host that will consume the images.

## 1. Identify the board and firmware

ESP32-S3 camera boards (XIAO ESP32S3 Sense, ESP32-S3-EYE, Freenove/generic
ESP32-S3-CAM, …) usually ship an **OV2640** (2 MP) or **OV5640** (5 MP, autofocus on some
modules) with 8 MB PSRAM. Note the board name, sensor, lens FOV and whether focus is fixed.
These numbers decide what is achievable.

Pick one transport to test:

| Firmware | How to get it | Probe command |
|---|---|---|
| `CameraWebServer` (Wi-Fi, recommended start) | Arduino IDE → *File → Examples → ESP32 → Camera → CameraWebServer*; select your board's `CAMERA_MODEL_*`, enable PSRAM, set SSID | `info`, `bench`, `sweep`, `stream` |
| USB webcam (UVC) | ESP-IDF `esp-iot-solution` `usb_device_uvc` example (S3 has native USB) | `uvc --index N` |
| Any MJPEG URL | — | `stream --url ...` |

UVC over USB removes Wi-Fi latency and jitter, and makes the S3 look like the existing
webcam to `camera_calibration`. Test it if Wi-Fi numbers disappoint.

## 2. Explore it in the GUI

```bash
python tools/esp32_camera_gui.py --host 192.168.1.42 --open   # CameraWebServer
python tools/esp32_camera_gui.py --uvc 1 --open               # S3 flashed as USB webcam
```

The GUI is a local web server on `http://127.0.0.1:8000`, and it is the only process that
owns the camera. It shows:

- the live view with ArUco and chessboard detections drawn on it
- live frame rate, frame-interval p50/p95/max, stalls over 250 ms and reconnects
- sharpness, brightness, temporal noise and clipped pixels
- every CameraWebServer sensor control: resolution, JPEG quality, exposure, gain, white
  balance, lens correction, mirror/flip and colour bar
- one-click snapshot benchmark and resolution sweep, with the stream paused while they
  run and the original resolution restored afterwards

Snapshots and `report.json` files go to `runs/esp32_gui/`. Temporal noise is only
meaningful when the scene is static.

No board yet? `python tools/esp32_camera_mock.py --port 8080` emulates CameraWebServer
with a synthetic scene: a moving cube with an ArUco tag, a chessboard, and Wi-Fi-like
latency and stalls. Point the GUI at it with `--host 127.0.0.1:8080`. Its numbers are
**not** ESP32 measurements.

## 3. Run the probe from the command line

```bash
H=192.168.1.42                       # IP printed on the ESP32 serial monitor
P=tools/esp32_camera_probe.py
python $P info  --host $H                                     # sensor settings
python $P sweep --host $H --framesizes 6,8,10,11,12,13 -n 20  --json runs/esp32/sweep.json
python $P bench --host $H -n 100 --save runs/esp32/frames     --json runs/esp32/bench_vga.json
python $P stream --url http://$H:81/stream --duration 60      --json runs/esp32/stream.json
```

Run `bench`/`stream` with these scenes, keeping each one static:

1. **Workspace view**: camera at its intended side-view mount, looking at the gripper and cube.
2. **Marker at working distance**: a printed `DICT_4X4_50` marker (`--aruco-dict` must
   match the printed one) on the cube. Read `aruco_detect_rate` and `aruco_min_edge_px`.
   Keep the marker away from the frame edge: OpenCV rejects noisy candidates near the border.
3. **Chessboard**: `--chessboard 9x6` (match `camera_calibration`). Tells you whether
   intrinsic calibration at this resolution is practical.
4. **Lighting**: repeat (1) under the dimmest lab lighting. Watch `brightness`, `clipped_pct`
   and `temporal_noise`.
5. **Soak**: `stream --duration 600`. Count `stalls_over_250ms` and errors, and note whether
   the board browns out or overheats. Power it from a solid 5 V supply, not a laptop hub port.

`sweep` restores the original framesize when it finishes. The framesize enum differs
between esp32-camera releases, so trust the decoded `resolutions` field, not the name.

## 4. What to look at

| Metric (report field) | Why it matters here | Auxiliary-view gate (proposed) |
|---|---|---|
| `latency_ms` p50/p95 (snapshot) | Observation age at the preflight/verify checks | p95 small next to the time the arm pauses at a phase boundary |
| `fps`, `interframe_ms`, `stalls_over_250ms` (stream) | Whether a live verify view is possible | No stalls at the chosen size during the soak |
| `error_count`, reconnects | `CameraSource` must time out and reconnect cleanly | Recovers without a power cycle |
| `aruco_detect_rate`, `aruco_min_edge_px` | Tag visibility for presence and coarse pose | Stable detection at working distance |
| `sharpness`, `temporal_noise`, `clipped_pct` | Image quality and lighting margin | Compare across sizes and settings, not absolute |
| `chessboard_detect_rate` | Calibratability at runtime resolution | Board detected across the working area |

These gates are proposed, not measured. Set the numbers once the first run gives a baseline.
Keep the resolution, JPEG quality, AEC/AGC and white balance fixed between calibration and
runtime (`/control?var=...`). Record them with `info`.

## 5. Known constraints to confirm or rule out

- **No hardware timestamp or clock sync.** Use host receive time minus measured latency (the
  perception plan says this explicitly). Frame-to-arm sync tighter than the latency jitter
  isn't possible.
- **JPEG artifacts and rolling shutter** with the OV2640 hurt corner accuracy. Expect higher
  reprojection error than the webcam's 0.82 px.
- **Wi-Fi is shared.** Latency tails grow with network load. Measure in the real lab, not
  on a quiet bench.
- **The camera server is single-client.** Holding `:81/stream` open can block `/capture`
  on some firmware versions. Only one host process should own the camera.

## 6. Results

| Date | Board / sensor | Transport | Resolution | Snapshot p50/p95 ms | Stream fps | ArUco rate @ distance | Notes |
|---|---|---|---|---|---|---|---|
| | | | | | | | |
