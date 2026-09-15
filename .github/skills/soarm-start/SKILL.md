---
name: soarm-start
description: 'Entry point and router for the soarm-ws workspace (SO-ARM100/SO-101 robot arm). Use FIRST whenever the user names a SO-ARM/SO-101 task — servos, calibration, teleop, IMU, camera, dataset recording, imitation learning, RL training, TAMP planning — or asks where something lives. Maps the eight submodules, names the exact package, install command and entry point, then dispatches to the right soarm-* skill.'
---

# SO-ARM Workspace — Start Here

_Arguments: say what you want to do (drive servos, calibrate, teleoperate, record a
dataset, train a policy, plan a pick-and-place) and whether hardware is connected._

## When to Use

- The user says "work on SO-ARM", "the arm", "SO-101", "let's run this", "where is X".
- A task is named but the package, install method, or entry point is not yet fixed.
- You are about to `cd` or `pip install` and are not certain which submodule owns it.

Run **Orientation**, then hand off per **Dispatch**. Do not start editing before
Dispatch — this workspace has eight repos with three different install methods and
two different servo transports; correct work in the wrong package is the standard
failure here.

## Orientation — the eight submodules

Workspace root: `/Users/thanhndv212/Develop/soarm-ws/` — a **thin umbrella repo**.
No root `pyproject.toml`, no root build tool, no workspace test command. Its only
job is pinning submodule commits together.

| Directory | What it is | Install | Skill |
|---|---|---|---|
| `soarm_sdk/` | Servo transport + `RobotInterface`. The foundation everything else drives hardware through. | `pip install -e soarm_sdk/` (hatchling, `src/`) | `soarm-sdk` (calibration workflow: `calibrate`) |
| `imu_sdk/` | IMU serial reader + Arduino firmware (M5StickC / ESP32+MPU) | `pip install -e imu_sdk/` | `soarm-imu-sdk` |
| `m5teleop/` | 50 Hz IMU teleoperation loop — the integration point | `pip install -e m5teleop/` | `soarm-m5teleop` |
| `camera_calibration/` | Camera intrinsics + ArUco tooling, standalone | `pip install -e camera_calibration/` | `soarm-camera-calibration` |
| `soarm_lerobot/` | Dataset recording + imitation learning (ACT) | `pip install -e soarm_lerobot/` | `soarm-lerobot` |
| `soarm_mjlab/` | RL training in MuJoCo via mjlab | **`uv sync`, not pip** | `soarm-mjlab` |
| `soarm_tamp/` | Long-horizon TAMP (`long_tamp`/HPP) → physical SO-101 | `pip install -e soarm_tamp/[host]` | `soarm-tamp` |
| `SO-ARM100/` | Vendored hardware repo (URDF, MJCF, STL, STEP) — **read-only** | not Python | — |

Cross-package concerns — submodule bumps, install order, lint/test/CI, releases —
belong to **`soarm-workspace`**. SO-101 tick-to-URDF-frame calibration — reference-pose
zeroing, ROM measurement, acceptance tolerances — belongs to **`calibrate`**, not to
`soarm-sdk` directly.

## Dispatch

| User wants | Invoke | Working directory |
|---|---|---|
| Talk to servos, read/write joints, joint limits, the dashboard, servo IDs/EEPROM | **`soarm-sdk`** | `soarm_sdk/` |
| Calibrate tick ↔ URDF frame, reference-pose zeroing, ROM measurement, acceptance tolerances | **`calibrate`** | `soarm_sdk/` |
| Read the IMU, flash IMU firmware, no data on the serial port | **`soarm-imu-sdk`** | `imu_sdk/` |
| Teleoperate the arm, tune the EKF, orientation control, IK | **`soarm-m5teleop`** | `m5teleop/` |
| Camera intrinsics, ArUco markers, chessboard capture | **`soarm-camera-calibration`** | `camera_calibration/` |
| Record demonstrations, LeRobotDataset, train ACT | **`soarm-lerobot`** | `soarm_lerobot/` |
| RL training/playback in simulation, MuJoCo, PPO, GPU runs | **`soarm-mjlab`** | `soarm_mjlab/` |
| Plan a pick-and-place, TCP-pose reach, HPP container, the plan-and-run dashboard, execute a manifest | **`soarm-tamp`** | `soarm_tamp/` |
| Submodule bump, install order, cross-package change, CI, release | **`soarm-workspace`** | repo root |

If the request spans packages (e.g. "record a dataset while teleoperating"), start
with the package that owns the *entry point* — here `soarm-m5teleop`, since
`teleop.py --record` drives `soarm_lerobot`, not the other way around.

## Hard rules — the recurring bugs in this workspace

1. **The physical arm is an SO-101, not an SO-100.** `SO-ARM100/Simulation/` ships
   both revisions. Default to `SO101/so101_new_calib.urdf` and `soarm_sdk`'s
   `configs/so101.yaml` for anything touching real hardware. `soarm_sdk`'s viser
   dashboards (`soarm-dashboard`, `soarm_tamp`'s plan-and-run dashboard) now default
   to the SO101 URDF too, mapped through the arm's saved calibration — there is no
   live SO100 reference left in this workspace's runtime paths.
2. **Always say which joint frame a radian value is in.** Three conventions are
   live — raw servo ticks, lerobot normalized degrees, the URDF kinematic zero — and
   they have been silently conflated more than once (mixed-frame joint limits once
   clamped 55% of a planned trajectory). `soarm_sdk.calibration.frame` is the only
   thing that relates ticks to the URDF.
3. **Two ways to reach the servo bus**, both behind `soarm_sdk.RobotInterface`:
   `ServoRobot` (this SDK's own Feetech stack) and `LeRobotRobot` (lerobot's
   `SOFollower`, calibration in servo EEPROM). Pick by transport, never by call-site
   API.
4. **`soarm_mjlab` uses `uv`.** `pip install -e` will not route its CPU/CUDA torch
   extras. Every other package is plain pip.
5. **Install `soarm_sdk` first.** `m5teleop` and `soarm_tamp[host]` depend on it; a
   missing local install silently pulls the PyPI copy instead of this checkout.
6. **Never push to `SO-ARM100/`** — upstream, read-only.
7. Each package has its own `CHANGELOG.md`. Read it before `git log`-spelunking.

## Environment facts

- Python ≥3.10 workspace-wide (`soarm_sdk` ≥3.9, `soarm_tamp` ≥3.11).
- The author's conda env is **`gosim`**.
- **pinocchio** must come from conda (`conda install -c conda-forge pinocchio`), not
  pip; `m5teleop` hard-depends on it. **quadprog** may need `brew install gfortran`.
- **`long_tamp` / `pyhpp` are not host-installable** — they exist only inside the
  HPP Docker container (`soarm_tamp/scripts/hpp_container.sh`).

## Reference docs

`README.md` (root, current) — workspace overview, package table, dashboard
screenshots; `AGENTS.md` (root, current) — install/test/run runbook; `ARCHITECTURE.md`
(root, predates `soarm_tamp`/`soarm_mjlab` — its dependency graph still says "six
packages"); `CHANGELOG.md`; `SOARM_MJLAB_ROADMAP.md` (active); `archive/MIGRATION_PLAN.md`,
`archive/TELEMETRY_PLAN.md` (both fully implemented, kept for history).
