# Architecture

This document describes how the packages in this workspace fit together. For
setup/build/test commands, see [AGENTS.md](AGENTS.md).

## Workspace shape

`soarm-ws` is a **thin umbrella repo** over six independently-versioned,
independently-installed Python packages, each tracked as a **git submodule**
with its own GitHub remote. There is no root package, no shared
`pyproject.toml`, and no build orchestration — the root repo's only job is to
pin compatible commits of the submodules together and document how they
compose.

```
soarm-ws/
├── soarm_sdk/           servo transport + register-level control (Feetech STS/SCS)
├── imu_sdk/             IMU transport + firmware (M5StickC / ESP32 + MPU)
├── m5teleop/            teleoperation pipeline — the integration point
├── soarm_learn/         dataset recording + imitation-learning training
├── camera_calibration/  standalone camera intrinsics / ArUco tooling
└── SO-ARM100/           read-only hardware repo (URDF, MJCF, CAD) from TheRobotStudio
```

Five of the six packages (`soarm_sdk`, `imu_sdk`, `m5teleop`, `soarm_learn`,
`camera_calibration`) are real, importable Python packages installed with
`pip install -e`. `SO-ARM100` is not Python — it's the hardware vendor's repo,
vendored in for its URDF/MJCF robot models and used read-only.

## Dependency graph

```
        imu_sdk            soarm_sdk
           │                    │
           │ (ImuReader,        │ (ArmInterface wraps
           │  ImuData)          │  lerobot SO100Follower,
           │                    │  itself independent of
           ▼                    ▼  soarm_sdk at import time)
        ┌─────────────────────────┐
        │        m5teleop          │◄── SO-ARM100 (URDF for pinocchio/viser FK)
        │  (imports imu_sdk        │
        │   directly; talks to     │
        │   servos via lerobot,    │
        │   not soarm_sdk)         │
        └───────────┬──────────────┘
                     │ optional: --record flag
                     ▼
              soarm_learn
        (TeleopRecorder buffers frames →
         LeRobotDataset; dataset.py feeds
         ACT / Diffusion Policy training)

        camera_calibration  — standalone, no dependency on the above
```

Notes on this graph:
- **`m5teleop` is the only package that imports another workspace package
  directly** (`from imu_sdk import ImuData, ImuReader, find_port` in
  `teleop.py`). Everything else is glued together at the process/CLI level,
  not the import level.
- **`soarm_sdk` and the teleop pipeline are parallel, not layered.**
  `m5teleop/m5teleop/lerobot_soarm_interface.py` (`ArmInterface`) talks to the
  servo bus through **lerobot's `SO100Follower`**, not through `soarm_sdk`.
  `soarm_sdk` is a separate, self-contained SDK used by its own examples
  (`calibrate.py`, `viser_dashboard.py`) for low-level register access,
  homing, and PID tuning — it is not currently wired into the teleop loop.
  Treat them as two independent ways to talk to the same Feetech servo bus,
  not as a dependency chain.
- `soarm_learn`'s `TeleopRecorder` import in `teleop.py` is wrapped in a
  `try/except ImportError` — recording is an optional add-on, not a hard
  dependency of teleop.
- `soarm_sdk`'s own README documents a `fullstack_manip/core/hardware_interface.py`
  (`ServoHardwareInterface`, `RobotInterface`, `MotionExecutor`) — **this code
  does not exist in this repo.** It's carried over from the SDK's upstream
  project (`github.com/thanhndv212/fullstack-manip`, see its `pyproject.toml`
  `Homepage`). Don't expect to find `fullstack_manip` here.

## Package details

### `soarm_sdk` — servo transport SDK

`src/` layout, packaged with **hatchling**, imported as `from soarm_sdk import
...`. Requires Python ≥3.9 (looser than the rest of the workspace).

- `port_handler.py`, `protocol_packet_handler.py`, `group_sync_read.py`,
  `group_sync_write.py`, `stservo_def.py` — the Feetech STS/SCS serial
  protocol implementation (packet framing, checksums, register map).
  `sts.py` / `scscl.py` provide protocol-specific convenience wrappers on top.
- `bus.py` — the hardware-access layer everything else is built on: port
  discovery/scanning, servo diagnostics, raw register `write1`/`write2`.
  Docstring in the file calls this out explicitly as "shared by all
  higher-level tools."
- `calibration.py` — batch operation planning (`OperationPlan`,
  `build_operation_plan`, `apply_plan`) for ID reassignment, angle limits,
  acceleration/speed, torque, mode, and baud rate changes across many servos
  in one pass. Backs the `calibrate.py` CLI and the dashboard's Reconfigure
  tab.
- `conversions.py` — the only math boundary between encoder ticks (0–4095)
  and SI units (radians, rad/s). Anything reading/writing joint state should
  go through here rather than hard-coding `4096`/`2048`.
- `examples/viser_dashboard.py` — a 7-tab browser control panel (Start Up,
  Homing Wizard, PID Tuning, Command Panel, Recorder, Monitor, Reconfigure)
  built on Viser, with live 3-D FK rendered via `yourdfpy`/`trimesh` against
  `SO-ARM100/Simulation/SO100/so100.urdf`. Polls all joints per cycle with a
  single `GroupSyncRead` bus transaction (falls back to per-servo reads on
  failure).

### `imu_sdk` — IMU transport SDK + firmware

Flat layout, imported as `from imu_sdk import ...`. Pairs Arduino firmware
with a Python reader.

- `firmware/m5imu_firmware/` — M5StickC Plus 1.1 (MPU6886, 6-axis).
- `firmware/esp32_mpu/` — generic ESP32 + MPU6050/6500 (6-axis) or
  MPU9250/9265+AK8963 (9-axis), selected by a `#define` at the top of the
  `.ino` file.
- Both firmware variants stream JSON lines at ~100 Hz over 115200-baud USB
  serial and perform **gyro bias calibration** at boot (500 samples, ~2.5 s,
  device must be still) before subtracting the bias from every sample.
- `imu_sdk/imu_data.py` — `ImuData` dataclass. `pitch`/`roll`/`yaw` fields
  exist but are always `0.0` from firmware — **orientation is computed on the
  host**, not the device (that's `m5teleop`'s ESKF).
- `imu_sdk/reader.py` — `ImuReader` (sync iteration, `read_one()`, or
  callback/background-thread mode via `.start()`) and `find_port()` for
  auto-detection. Silently filters non-data packets (boot/calibration/error
  lines) so only valid `ImuData` surfaces to callers.

### `m5teleop` — the integration point

This is where the other packages meet. A 50 Hz real-time loop
(`teleop.py`) wires together:

```
IMU (imu_sdk.ImuReader)
  → ImuEKF            (imu_ekf.py)      error-state Kalman filter, ZARU bias correction
  → OrientationController (orient_controller.py)  two-layer cascade P-P, quaternion
  → IKSolver           (ik_solver.py)    differential IK via pink + pinocchio
  → ArmInterface       (lerobot_soarm_interface.py)  wraps lerobot SO100Follower → real servos
  → SimInterface        (sim_interface.py)  parallel viser 3-D browser sim
  → TeleopVisualizer    (viz.py)         logs everything to Rerun
```

Supporting modules: `config.py` (every tunable parameter in one place —
EKF noise/gate thresholds, LPF alpha, etc.), `lpf.py` (single shared EMA
low-pass filter used everywhere raw IMU data needs smoothing),
`imu_twist.py` (legacy IMU→6D-twist converter, kept but unused by the current
cascade-controller design).

- **Buttons**: BTN_A toggles teleop on/off (also delimits recorded episodes),
  BTN_B toggles the gripper.
- **`--record` flag** hooks in `soarm_learn.TeleopRecorder` to buffer frames
  and write LeRobotDataset episodes alongside the live control loop, gated by
  an optional import so teleop works without `soarm_learn`/`lerobot`
  installed.
- **`tune_ekf.py`** is a separate offline tool: record a stationary IMU
  session, then grid-search (and optionally scipy fine-tune) the ESKF noise
  parameters against it.
- Full phase-by-phase build log and tuning guide:
  [`m5teleop/IMPLEMENTATION.md`](m5teleop/IMPLEMENTATION.md) (476 lines) —
  read this before touching the EKF or orientation controller, it documents
  *why* each parameter has its current value.

### `soarm_learn` — dataset recording + imitation learning

Flat layout, depends on `torch`, `lerobot`, `datasets`.

- `recorder.py` — `TeleopRecorder`, the only symbol re-exported at package
  level. Buffers per-frame joint/gripper/task data from the teleop loop,
  detects episode boundaries (BTN_A toggling teleop), writes LeRobotDataset
  episodes (parquet + metadata), and auto-discards short/noise episodes.
- `dataset.py` — loads recorded LeRobotDataset episodes into torch
  `Dataset`/`DataLoader`s, with normalization and chunking for **ACT** and
  **Diffusion Policy** training.
- `scripts/record.py` / `scripts/train.py` — installed as console scripts
  `soarm-record` / `soarm-train`.
- This package is consumed by `m5teleop` (recording) but never imports
  `m5teleop`, `soarm_sdk`, or `imu_sdk` itself — it operates purely on
  LeRobotDataset data, decoupled from how that data was produced.

### `camera_calibration` — standalone vision tooling

Flat layout. Not wired into the teleop pipeline or any other package in this
workspace — used independently for camera intrinsics and ArUco marker work
(e.g. for future eye-in-hand or workspace-calibration features).

- `calibrator.py` — chessboard intrinsic calibration (auto or manual capture).
- `detector.py` — live ArUco detection monitor.
- `markers.py` — ArUco marker/sheet PNG generation (no display dependency).
- `estimator.py` — webcam parameter estimation from presets or live detection.
- `_viz.py` — all visualization goes through **Rerun**; there is no
  `cv2.imshow`/matplotlib path anywhere in this package, including headless
  operation via `--no-spawn`.
- `__main__.py` — unified CLI with 7 subcommands (`capture`, `calibrate`,
  `detect`, `generate`, `estimate`, `record`, `view`).
- Calibration results are saved as JSON under `data/` (camera matrix, distortion
  coefficients, resolution, reprojection error, metadata).

### `SO-ARM100` — hardware vendor repo

Vendored from `TheRobotStudio/SO-ARM100`, **read-only** (don't push changes
here). Supplies the robot description consumed by two other packages:
- `Simulation/SO100/so100.urdf` — used by `soarm_sdk`'s viser dashboard (FK
  via `yourdfpy`/`trimesh`) and by `m5teleop`'s IK solver (`pink`/`pinocchio`).
- `Simulation/scene.xml` — MuJoCo MJCF for physics simulation.
- Also contains CAD (STEP/STL), 3D-print notes, and the BOM/assembly docs for
  the physical arm itself.

## Cross-cutting patterns worth knowing before you edit

- **Two independent servo-control stacks.** `soarm_sdk` (raw Feetech
  protocol) and lerobot's `SO100Follower` (used by `m5teleop`) both talk to
  the same physical bus but are not integrated with each other in this repo.
  If you're adding a feature that needs joint state in teleop, use the
  `ArmInterface` in `lerobot_soarm_interface.py`, not `soarm_sdk` directly.
- **Config centralization.** Each package that has runtime-tunable behavior
  keeps it in one `config.py` (`m5teleop/m5teleop/config.py`,
  `soarm_learn/soarm_learn/config.py`) rather than scattering constants.
- **Rerun as the universal viewer.** Both `m5teleop` (`viz.py`) and
  `camera_calibration` (`_viz.py`) standardize on Rerun for live
  visualization/logging instead of ad hoc GUI windows.
- **Optional imports for optional hardware/features.** Patterns like
  `try: from soarm_learn import TeleopRecorder / except ImportError` appear
  wherever a feature (recording, magnetometer data, viser extras) is
  optional — check for this before assuming a dependency is required.
