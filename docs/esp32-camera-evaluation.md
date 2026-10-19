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
| USB webcam (UVC) | ESP-IDF `esp-iot-solution` `usb_webcam` example (S3 has native USB); see [§2a](#2a-flash-it-as-a-usb-webcam-uvc) | `uvc --index N` |
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
- one-click snapshot benchmark, resolution sweep and stream sweep (live fps, gaps, stalls,
  and glass-to-host lag with the `/clock` page in view), with the stream paused while they
  run and the original resolution restored afterwards

Snapshots and `report.json` files go to `runs/esp32_gui/`. Temporal noise is only
meaningful when the scene is static.

No board yet? `python tools/esp32_camera_mock.py --port 8080` emulates CameraWebServer
with a synthetic scene: a moving cube with an ArUco tag, a chessboard, and Wi-Fi-like
latency and stalls. Point the GUI at it with `--host 127.0.0.1:8080`. Its numbers are
**not** ESP32 measurements.

## 2a. Flash it as a USB webcam (UVC)

Tested on the Freenove ESP32-S3-WROOM CAM (N8R8) with ESP-IDF v5.4.2 and
`esp-iot-solution`'s `examples/usb/device/usb_webcam` (`usb_device_uvc` 1.3.1, MJPEG only).
The board config is [`tools/esp32_uvc/sdkconfig.freenove`](../tools/esp32_uvc/sdkconfig.freenove):
ESP32-S3-EYE camera pins as a *custom* module (choosing the EYE board pulls in its LCD
driver), VGA at 30 fps requested, isochronous transfer (works on macOS; bulk is faster but
has Linux host issues).

```bash
. ~/esp/esp-idf/export.sh
cd ~/esp/esp-iot-solution/examples/usb/device/usb_webcam
cp <soarm-ws>/tools/esp32_uvc/sdkconfig.freenove .
D="sdkconfig.defaults;sdkconfig.freenove"
idf.py -D SDKCONFIG_DEFAULTS="$D" set-target esp32s3
idf.py -D SDKCONFIG_DEFAULTS="$D" reconfigure build
```

The board has two USB-C ports. Flash through the **CH343 USB-serial port**
(`/dev/cu.usbmodem…`, "USB Single Serial"). Auto-reset into download mode doesn't work on
this board: hold BOOT, tap RST, release BOOT, then

```bash
cd build && python -m esptool --chip esp32s3 -p /dev/cu.usbmodemXXXX -b 460800 \
  --before no_reset --after hard_reset write_flash @flash_args
```

Then move the cable to the **native USB port** (GPIO19/20). It enumerates as
"ESP32-S3 UVC Camera" (macOS lists it as "UVC CAM1"). The OpenCV index depends on what else
is attached: with the FaceTime and Continuity cameras present it was index 0. On macOS the
process that opens it needs camera permission, so run the probe or GUI from Terminal.app,
not from a sandboxed shell.

The firmware fixes the JPEG quality per size (VGA = 12) and turns on vflip. There are no
`/control` endpoints in UVC mode, so the GUI's sensor tab doesn't apply. To change size or
quality, rebuild.

**Going back to Wi-Fi:** reflash the CameraWebServer sketch, or write a saved merged image
at `0x0` in download mode. A merged image built from the sketch contains the Wi-Fi
credentials: keep it out of the repo.

## 3. Run the probe from the command line

```bash
H=192.168.1.42                       # IP printed on the ESP32 serial monitor
P=tools/esp32_camera_probe.py
python $P info  --host $H                                     # sensor settings
python $P sweep --host $H --framesizes 6,8,10,11,12,13 -n 20  --json runs/esp32/sweep.json
python $P bench --host $H -n 100 --save runs/esp32/frames     --json runs/esp32/bench_vga.json
python $P stream --url http://$H:81/stream --duration 60      --json runs/esp32/stream.json
```

**Live-stream lag per resolution, without switching by hand.** `sweep` times `/capture`
snapshots, which is not what the live view feels like. `stream-sweep` sets each framesize,
records the MJPEG stream for `--duration` seconds, then analyses it, so the measurement
doesn't throttle the stream. It reports fps, frame-gap p50/p95/max and stalls per size, and
restores the original size afterwards. For **glass-to-host lag**, open the lag clock
full-screen on the machine that runs the benchmark: a marker whose ID changes every 100 ms,
driven by that machine's clock. Point the camera at it, keep other markers out of view, and
add `--clock`:

```bash
python $P clock-page --out runs/esp32/clock.html     # open full-screen; the GUI also serves /clock
python $P stream-sweep --host $H --clock --duration 10 --json runs/esp32/stream_sweep.json
```

Each lag sample is quantised to ±50 ms, but the median is not. The lag includes the screen's
own display delay (about one refresh), so it is an upper bound on the camera's lag. If the
marker's ID doesn't cycle, for example a printed tag, the run is flagged and gives no lag.
The GUI runs the same thing with **Run stream sweep** (tick *Measure lag*).

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
| 2026-10-19 | Freenove ESP32-S3-WROOM CAM (N8R8); sensor OV3660/OV5640-class (from `/status` registers, unconfirmed) | Wi-Fi, CameraWebServer (arduino-esp32 3.3.12) | 320x240 (QVGA), q=10 | 49 / 70 (30/30 ok) | 27.5 live, 20.7 snapshot | 93 % (28/30), ID 7, min edge ≈ 70 px | Preliminary: marker shown on a laptop screen at about 40 cm, not on the cube; image soft (sharpness 96, sd 40); temporal noise 34 means the scene wasn't static; no chessboard in view. Rerun at VGA+ on the side-view mount. |
| 2026-10-19 | same | same | Sweep 320x240 → 1280x720, q=10, n=10 each | 320x240: 52/134 · 400x296: 31/66 · **640x480: 44/58** · 800x600: 52/66 · 1024x768: 76/103 · 1280x720: 86/174 (all 10/10 ok) | snapshot 17.8 / 28.2 / **22.9** / 18.4 / 12.7 / 10.1 | n/a: marker not in view during the sweep (handheld camera) | Latency and rate only. JPEG 6.7 → 41.5 KB. VGA has the tightest p95 and a usable rate; it's the size to try for the side view. At 1024x768 and up, p95 passes 100 ms. The live stream logged 7 stalls over 250 ms during the session (not a soak). |
| 2026-10-19 | same | same, live MJPEG stream (`stream-sweep --clock`, 10 s per size) | 320x240 → 1280x720, q=10 | n/a (stream) | 25.8 / 23.7 / **20.2** / 16.2 / 8.9 / 11.2 | Lag clock read in 73–80 % of frames (marker on the Mac screen, not full-screen) | Glass-to-host lag p50/p95 ms: 127/180 · 130/181 · **140/191 (VGA)** · 158/218 · 245/381 (XGA) · 183/242 (HD). Includes the screen's display delay. No stalls or errors at any size. XGA is worse than HD on every measure: avoid it. About 130 ms of lag at any size comes from the camera and Wi-Fi, not resolution. Sharpness 38 → 5 with size: lens out of focus, refocus before the ArUco test. |
| 2026-10-19 | same | **USB UVC** (esp-iot-solution `usb_webcam`, ESP-IDF 5.4.2, isochronous) | 640x480, MJPEG q=12 (firmware fixed) | n/a (stream) | 19.7 (10 s, 177 frames) | n/a: no marker in view | Frames arrive in **bursts**: interframe p50 0.8 ms, p95 248 ms, max 252 ms (1 gap over 250 ms), i.e. about 5 frames every 250 ms. No lag-clock run yet. Camera pointed at the ceiling: sharpness 3.0 is the scene plus the defocused lens, not comparable with the Wi-Fi rows. Same frame rate as Wi-Fi VGA (20.2), so USB alone doesn't buy throughput; the gain to test is lag and jitter. |
