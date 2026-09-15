---
name: soarm-camera-calibration
description: 'Work in camera_calibration — standalone OpenCV camera intrinsics and ArUco tooling with Rerun visualisation. Use for capturing chessboard calibration images, computing or loading intrinsics, live ArUco detection, generating marker PNGs or sheets, pose estimation, or the camera-calibration CLI. Independent of the rest of soarm-ws — no arm or IMU needed.'
---

# camera_calibration — Intrinsics & ArUco

Path: `camera_calibration/` · v0.1.0 · setuptools, flat layout · Python ≥3.10 ·
deps `opencv-python`, `numpy`, `rerun-sdk`

**Standalone.** It has no dependency on `soarm_sdk`, `imu_sdk`, or anything else in the
workspace, and nothing depends on it. Treat it as its own project that happens to live
here — cross-package rules from `soarm-workspace` mostly don't apply.

## The CLI — `camera-calibration <subcommand>`

Installed as a console script (`camera_calibration.__main__:main`). Five subcommands:

| Subcommand | Does | Key flags |
|---|---|---|
| `capture` | Capture calibration images and compute intrinsics | `--images 20`, `--pattern-size 10x7`, `--square-size 0.025`, `--output STEM`, `--manual` |
| `calibrate` | Load and display an existing calibration | `--calibration-file` (**required**), `--test` |
| `detect` | Live ArUco detection monitor | `--dictionary DICT_6X6_250`, `--highlight 0 …` |
| `generate` | Generate ArUco marker PNG(s) | `--marker-id`, `--size 400`, `--dict`, `--output`, `--sheet N`, `--no-display` |
| `estimate` | Estimate camera parameters | `--camera` |

All take `--camera ID` (default `0`). There is a shared **rerun** argument group for
visualisation — Rerun is the display path throughout, not `cv2.imshow` windows.

Defaults worth knowing before debugging a failed capture: pattern is **10x7 inner
corners**, square size **25 mm**, and the default ArUco dictionary is
**`DICT_6X6_250`**. A detection that finds nothing is usually a pattern-size or
dictionary mismatch, not a camera problem.

## Module map

```
__main__.py    argparse CLI, subcommand wiring
calibrator.py  intrinsics computation / calibration objects
detector.py    ArUco detection
markers.py     marker generation
estimator.py   camera parameter / pose estimation
_shared.py     shared helpers (tested)
_viz.py        Rerun visualisation
patterns/      chessboard_pattern.png + pre-generated ArUco marker PNGs
data/          dated calibration outputs (.json + .csv), plus a figaroh-format export
```

`patterns/` is the printable input side, `data/` the output side. `data/README.md`
documents the capture sessions. One artifact there
(`camera_calibration_20250607_174327_figaroh.py`) is an export for the FIGAROH
calibration toolbox in the sibling `figaroh-ws` workspace — if the user asks about
robot-camera calibration downstream of this, that is the link.

## Testing

```bash
cd camera_calibration && pytest tests/ -v
```

`tests/test_shared_helpers.py`, `tests/test_camera_window.py` — hardware-free. No CI.
Lint with `ruff check` (see the ruff caveat in `soarm-workspace`).

Keep new tests off the camera: anything requiring a live `--camera 0` cannot run in
this suite.

## Traps

- Relicensed Apache-2.0 → MIT along with `imu_sdk`.
- Changelog: `camera_calibration/CHANGELOG.md`. Read it before `git log`.
