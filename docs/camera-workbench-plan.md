# Camera workbench: one GUI for any camera and any calibration

Status: plan, 2026-10-20. Nothing here is implemented yet.

The goal is a single tool that opens any camera the project uses (USB webcam, ESP32 over Wi-Fi
or USB, a folder of images) and runs any calibration on it (intrinsics, camera-to-base,
hand-eye, camera-to-camera) with live feedback. Each run produces one versioned file that
`soarm_tamp` and later perception code can trust. It serves Stages 1, 2 and 8 of the
[perception plan](perception-tamp-integration-plan.md).

## 1. What exists today

### `camera_calibration` (submodule): a CLI with Rerun as a viewer, no real GUI

| Part | What it does | Limitation for a general tool |
|---|---|---|
| `__main__.py` | 7 subcommands: `capture`, `calibrate`, `detect`, `generate`, `estimate`, `record`, `view` | Each subcommand opens its own `cv2.VideoCapture(int)`, so there's no shared camera owner |
| `calibrator.py` `CameraCalibrator` | Chessboard capture (auto every 1.5 s, or Enter in the terminal), `calibrateCamera`, save JSON + pickle + FIGAROH `.py`, live undistortion test | Capture loop, detection, calibration solve and saving are all in one class. Resolution is hard-coded to 1280x720 for capture, while `--test` uses the camera default. Chessboard only, pinhole only. No per-view error, no held-out check, no coverage feedback. Ctrl-C is the only way to stop |
| `_viz.py` | Logs frames, status text and a Markdown result to Rerun | Rerun only displays. Every control is in the terminal |
| `detector.py` | Live ArUco monitor | Defaults to `DICT_4X4_50`, while `markers.py` defaults to `DICT_6X6_250` (perception plan decision 2) |
| `estimator.py` | Guesses intrinsics from FOV presets | Fine as a fallback; not a calibration |
| `_shared.py` | Finds and loads calibration JSON, with a heuristic fallback | The JSON has no camera identity and no capture settings, so a file can't be checked against the camera it's used with |

Smaller problems found while reading:
- `calibrator._parse_size` uses `argparse` at module level without importing it, so bad
  input raises a `NameError`.
- `save_calibration` reruns `calibrateCamera` with an intrinsic guess, so the saved RPE can
  differ from the printed one.
- The README says Apache-2.0 while `pyproject.toml` and `LICENSE` say MIT.

### The ESP32 GUI (`tools/esp32_camera_gui.py` + `.html`, since removed): a real GUI, but for one job

- A stdlib HTTP server plus one HTML page (no extra dependencies).
- **One camera owner thread**, with automatic reconnect.
- Live MJPEG preview, JSON state polling, and a one-screen layout with a stats strip and
  sidebar tabs.
- Background jobs (benchmark, sweeps), snapshots, ArUco and chessboard overlays.
- Sources are an HTTP MJPEG stream or a UVC index. The sensor controls only work with ESP32
  CameraWebServer.
- Every frame is analysed on the capture thread in Python, so the frame rate falls with
  size. On a generic webcam: about 5 fps at 1080p, 10 at 720p, 19 at VGA. That has to be
  designed out.
- It can't calibrate anything.

**Conclusion:** the calibration logic is in `camera_calibration`, and the usable GUI design
was in `tools/`. The workbench joins them: a GUI-free core in `camera_calibration`, and the
ESP32 GUI's server and page turned into a general front-end.

## 2. Design

```
camera_calibration/
  sources/      CameraSource: uvc, mjpeg_http, esp32 (adds controls), image_dir, video_file, mock
  capture.py    CaptureLoop: owner thread, latest-frame slot, timestamps, drop counts
  targets/      Chessboard, ChArUco, ArUco grid board, single marker: detect / draw / print
  procedures/   Intrinsics, Extrinsic(T_base_camera), HandEye, CameraToCamera, Validate, Benchmark
  artifact.py   versioned calibration file: read, write, check against a live camera
  workbench/    HTTP server + one HTML page (from esp32_camera_gui), optional Rerun sink
  __main__.py   existing subcommands kept, plus `workbench` and headless `solve`
```

### 2.1 Sources: "any camera"

```python
class CameraSource(Protocol):
    def open(self) -> SourceInfo: ...          # name, unique id, transport, resolution, fps
    def read(self) -> Frame: ...               # img, t_host, seq, encoded bytes if known
    def close(self) -> None: ...
    def controls(self) -> list[Control]: ...   # optional: exposure, gain, focus, JPEG quality...
    def set_control(self, name, value): ...
```

- **One URI picks the source**, so CLI, GUI and config files all use the same thing:
  `uvc:0?size=1280x720&fps=30`, `uvc:name=USB Camera`, `esp32:192.168.1.142`,
  `mjpeg:http://…/stream`, `dir:runs/calib01/`, `video:clip.mp4`, `mock:`.
- **Choose a camera by name, not by index.** Indices moved three times in this session as
  cameras were plugged in. Resolve the name to an index when the source is opened, and
  store the name and unique ID in the calibration file.
- **Controls are capability-based.** For UVC that means `CAP_PROP_*` exposure, focus and
  white balance, where the backend supports them (check on macOS, since AVFoundation exposes
  few). The ESP32 source keeps the existing `/control` mapping. The GUI draws whatever
  controls the source reports, which is how the ESP32-only Sensor tab becomes general.
- **`dir:` and `video:` sources let every procedure run offline.** That is how the tests run
  in CI, and how a calibration is re-solved later from saved images.
- The `soarm_lerobot` and `m5teleop` camera code can adopt the same protocol later. That is
  not part of this plan.

### 2.2 Capture loop: fix the frame-rate problem by design

Three stages, each never blocking the one before it:

1. **Capture thread:** reads as fast as the camera delivers, timestamps on receipt, and
   keeps the latest frame plus a drop counter. This is the single owner the perception plan
   asks for.
2. **Analysis worker:** takes the newest frame when it's free. Detection runs at its own
   rate, so slow detection no longer lowers the camera rate. Chessboard search runs on a
   downscaled image, then `cornerSubPix` refines at full resolution.
3. **Preview encoder:** sends the display stream downscaled to at most about 960 px wide,
   with the overlay drawn on top. Saved samples are always full resolution and unencoded.

The stats strip shows camera fps and analysis fps separately.

### 2.3 Targets

Each target has `detect(gray) -> Detection(ids, img_pts, obj_pts)`, `draw()` and
`render_printable(dpi, paper)`, plus a spec that is saved in the calibration file: type,
grid, square or marker size in metres, dictionary.

- **ChArUco** becomes the default for new calibrations. It works with partial views and
  OpenCV recommends it. The chessboard stays for the existing data.
- **One dictionary per project config**, which settles perception plan decision 2.
- The existing on-screen chessboard page (`patterns/chessboard_screen.html`) becomes a
  printable/displayable output of the target.

### 2.4 Procedures: "any calibration"

Every calibration runs through the same steps, which is what lets one GUI drive all of them:

```python
class Procedure(Protocol):
    needs: Needs                 # target, intrinsics, robot pose source, second camera
    def feedback(self, frame, det) -> Feedback: ...   # overlay, coverage, "move closer / tilt"
    def accept(self, frame, det) -> Sample | None: ...# auto: stable + new pose; or manual
    def solve(self, samples) -> Result: ...
    def validate(self, result, held_out) -> Report: ...
    def artifact(self, result, report) -> dict: ...
```

| Procedure | Solver | Extra input | Perception stage |
|---|---|---|---|
| Intrinsics (pinhole / fisheye) | `calibrateCamera` / `fisheye.calibrate` | none | 1 |
| Camera to base, fixed camera | `solvePnP` on a board at a measured base pose → `T_base_camera` | board-to-base transform | 2 |
| Hand-eye, wrist camera | `calibrateHandEye` | arm poses from `soarm_sdk` (`RobotInterface` → URDF forward kinematics) | 2 (later) |
| Eye-to-hand with robot pose | `calibrateRobotWorldHandEye` | same | 2 (alternative) |
| Camera to camera (webcam + ESP32) | PnP on a shared board, both views | second source, intrinsics for both | 8 |
| Time offset between cameras | lag clock (already in the probe) | screen with `/clock` | 8 |
| Validate | load a calibration file, check undistortion, held-out reprojection, "camera moved" check | calibration file | 1, 2 |
| Benchmark | the current ESP32 probe metrics (fps, gaps, lag, sharpness) | none | 8 |

The GUI walks through these steps for whichever procedure is chosen:

- **Feedback** draws a coverage heat map of where corners have landed, plus the pose
  spread (tilt and distance).
- **Accept** auto-captures when the board is steady and the view is new, or you capture by
  hand.
- **Results** show per-view error, can drop outliers, and re-solve.
- **Validate** is checked against held-out views.
- **Save** writes the calibration file.

Robot poses come only through `soarm_sdk.RobotInterface` (an optional `[robot]` extra).
Every transform is named by direction (`T_base_camera`) and joint angles are in URDF
radians, following the workspace rule that radian values must say which frame they're in.

### 2.5 Calibration file

One JSON schema with `schema_version`:

| Section | Contents |
|---|---|
| Camera | name, unique ID, transport |
| Capture settings | resolution, fps, codec, focus and exposure, JPEG quality |
| Target | target spec (§2.3) |
| Model and intrinsics | model, `K`, `D` |
| Extrinsics | named transforms, if any |
| Errors | per-view errors, held-out error |
| Inputs | sample image paths, robot pose source and calibration ID |
| Provenance | content hash, tool version |

- `load_calibration_parameters` keeps reading the existing `data/*.json` files.
- New code can call `artifact.check(source_info)` to refuse a file whose resolution or
  camera ID doesn't match. This is the "no resolution/focus mismatch" exit evidence of the
  perception plan.
- The pickle and FIGAROH outputs become optional exports.

### 2.6 Front-end

**Recommendation: keep the stdlib HTTP + single-HTML approach already built in this
branch,** with Rerun as an optional recording output (`--rerun-save`). Reasons:

- The approach is proven here for live video, stats, jobs and a one-screen layout.
- It has no dependencies.
- It works from any browser, including the in-app pane.
- The camera stays owned by one process.

Alternatives considered:
- **Rerun only:** it can't take input, so capture control would stay in the terminal.
- **viser:** `soarm_sdk` already uses it, and its 3-D scene would show `T_base_camera` and
  the camera view cone next to the URDF arm, which is attractive for the extrinsic and
  hand-eye steps. Its widget set is limited, and video over its websocket is unmeasured.
  Use it, or Rerun, only for the 3-D check view in the extrinsic phase, not for the main UI.

Layout, from the current GUI:
- **Header:** source selector (URI or a list of found cameras) and camera status.
- **Main area:** live view with an overlay toggle and, in calibration, the coverage heat map.
- **Stats strip:** camera fps, analysis fps, gaps, lag, sharpness, plus samples and current
  error while calibrating.
- **Sidebar tabs:** **Source** (controls drawn from capabilities), **Calibrate** (choose a
  procedure, then its steps), **Validate**, **Benchmark**.
- **Results dialog:** per-view error chart, save.

macOS camera permission: the process has to be started from a terminal app that has camera
access. `camera-calibration workbench` should print that hint when opening fails with the
authorization error.

## 3. Phases

| Phase | Work | Done when |
|---|---|---|
| 0. Clean up | Fix the `argparse` import, the RPE mismatch, the README license, and the default dictionary; init the submodule in this worktree | Existing tests pass; `capture` behaves as before |
| 1. Core | `sources/` (uvc with name lookup, mjpeg, esp32, dir, mock), `capture.py` three-stage loop, `artifact.py` | Tests on `mock:` and `dir:` in CI. On the generic webcam, camera fps at 1080p is close to what the probe measured, not 5 |
| 2. Workbench + intrinsics | Port the ESP32 GUI server and page onto the core (feature parity: live view, stats, sensor controls, benchmark). Add targets with ChArUco, the Intrinsics procedure with coverage and held-out check, and `solve --from dir:` | Calibrate the USB webcam and the ESP32 from the GUI; held-out error reported; the ESP32 GUI's benchmarks run in the workbench |
| 3. Camera to base | Extrinsic procedure, board placement file, 3-D check view, camera-moved check | Perception plan Stage 2 exit evidence |
| 4. Robot and multi-camera | Hand-eye via `soarm_sdk`, camera to camera, time offset | Wrist or ESP32 view expressed in the base frame with a measured error |

**Phase 1 result (2026-10-20):** done in `camera_calibration` (`sources/`, `capture.py`, `artifact.py`; 13 new tests on `mock:` and `dir:`). On the generic webcam via `uvc:name=USB Camera`: 1080p camera rate 20 fps, the camera's own rate in room light (was 4-5 in the old GUI); chessboard analysis 20 fps at 35 ms/frame with downscaled search, against 5 fps for a full-resolution search, which no longer slows the camera. Name lookup picked the right camera with three attached (USB, FaceTime, iPhone).

**Phase 2 result (2026-10-20):** partly done in `camera_calibration`. Done: `targets/` (ChArUco by default, `charuco?squares=7x5&square=0.03&marker=0.022&dict=DICT_4X4_50`, which prints at 230x180 mm and fits A4 landscape; chessboard too), `procedures/intrinsics.py` (coverage grid, auto-accept when the view is steady and new, every fifth view held out and reported), `workbench/` (server and page on `CaptureLoop`), and the `workbench`, `solve --from dir:` and `target` subcommands. Against the mock camera's ground truth, detected corners are within 0.08 px at 1080p and 0.3 px at VGA. Before the fix, ChArUco corners were biased by 0.9 px because `cornerSubPix` reached into the markers. A calibration from the page recovers fx within 0.1% (held-out error 0.03 px). The USB webcam runs in the workbench at 1080p: 20 fps camera, 20 fps ChArUco analysis. Not done yet:
- A real calibration of the webcam and the ESP32, which needs a printed board.
- ~~The benchmark jobs and the ESP32 GUI as a thin wrapper.~~ Done: the benchmarks moved
  into the workbench rather than being wrapped (below).

**ESP32 GUI port (2026-10-20):** everything in `soarm-ws/tools` now lives in
`camera_calibration`, and `tools/` is gone. `camera_calibration.bench` holds the metrics,
the lag clock and the stream, snapshot and sweep benchmarks; stream timing comes from
`CaptureLoop`'s per-frame receive times. The workbench page has a **Benchmark** tab: live
stream health and image-quality tiles, two-minute charts, and the four jobs, each writing
`report.json`. The **Source** tab has the ArUco/grid overlay and the full grouped ESP32
sensor controls. The CLI gained `bench`, `clock-page` and `esp32-mock`, and the UVC firmware
config moved to `camera_calibration/firmware/esp32_uvc/`. Against the mock CameraWebServer,
a stream sweep from the page gave 22.4 fps at QVGA and 14.0 at VGA, and it restored the
original size.

Phases 0–2 are self-contained in `camera_calibration`. Phase 3 needs the board-to-base
measurement. Phase 4 needs the arm.

## 4. Decisions to settle

1. **Location.** Settled: `camera_calibration` (the owning submodule) holds everything,
   ESP32 tools included; `soarm-ws/tools` was removed. The alternative is a new package,
   which adds install order and another submodule.
2. **Default target for new calibrations.** ChArUco (recommended) or chessboard. Either
   way, print a board with measured square size.
3. **Rerun's role.** An optional output (recommended), or kept as the default viewer for the
   existing subcommands. The subcommands keep working either way.

## 5. Not verified yet

- Mapping a camera name to an OpenCV index on macOS: AVFoundation's order usually follows
  `system_profiler SPCameraDataType`, but this needs a test with 3+ cameras attached.
- Which `CAP_PROP_*` controls (focus, exposure) the generic webcam honours through
  AVFoundation. The probe in `UVCSource` found none on the generic webcam, so the workbench
  shows no controls for it. Setting them may need a UVC-level tool, not OpenCV.
- viser image-streaming rate, if it's used for the 3-D view.
