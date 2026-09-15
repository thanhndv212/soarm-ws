# soarm-ws

A modular, full-stack workspace for the [SO-ARM100](https://github.com/TheRobotStudio/SO-ARM100)/SO-101
manipulator: servo/IMU transport, teleoperation, camera calibration, imitation learning, task-and-motion
planning, and MuJoCo-based RL training — each its own independently-versioned package, tracked here as
git submodules with no shared build system forcing them into lockstep.

**Project page:** https://thanhndv212.github.io/soarm-ws-webpage/ — architecture diagram and a full,
step-by-step breakdown of the teleoperation, RL training, and TAMP pipelines, with real numbers measured
on hardware.

## In action

<!--
  Pending: drop screenshots in and remove this comment.
  docs/images/calibration-dashboard.png — soarm_sdk's soarm-dashboard-calibration (Viser, 3-D FK + the
    four-tab guided calibration workflow: tolerances, signs, ROM/zeros, review & save)
  docs/images/tamp-dashboard.png — soarm_tamp's dashboard (Viser, TCP Plan / Pick & Place tabs: plan,
    preview via the ghost mesh, and execute against the real arm)
-->
| Calibration dashboard (`soarm_sdk`) | TAMP dashboard (`soarm_tamp`) |
|---|---|
| ![soarm-dashboard-calibration](docs/images/calibration-dashboard.png) | ![soarm_tamp dashboard](docs/images/tamp-dashboard.png) |

A short video of the real robot running a plan alongside the TAMP dashboard's mirrored arm is coming —
this section will get an embed once it's recorded.

## Packages

| Package | What it does |
|---|---|
| [`soarm_sdk`](soarm_sdk/) | Feetech STS/SCS servo protocol SDK — transport, batch calibration, EEPROM-limit tracking, and a Viser dashboard (setup, PID tuning, monitoring, guided calibration). |
| [`imu_sdk`](imu_sdk/) | Transport + firmware for M5StickC/ESP32 IMU boards feeding `m5teleop`'s attitude estimator. |
| [`m5teleop`](m5teleop/) | The teleoperation integration point: IMU → ESKF → cascade orientation controller → differential IK → servo dispatch, at 50 Hz. |
| [`soarm_lerobot`](soarm_lerobot/) | Dataset recording (from `m5teleop --record`) and ACT/Diffusion Policy training on the result. |
| [`camera_calibration`](camera_calibration/) | Standalone camera intrinsics + ArUco toolkit, Rerun-based, no shared dependencies. |
| [`soarm_tamp`](soarm_tamp/) | Task-and-motion planning on `long_tamp`/HPP, executing through `soarm_sdk`'s `ServoRobot` — planning (container) and execution (host) split across a process boundary, joined by a waypoint manifest. Pick-and-place has run end to end on hardware. |
| [`soarm_mjlab`](soarm_mjlab/) | RL training of SO-ARM100 in MuJoCo via [mjlab](https://github.com/mujocolab/mjlab), deploying through the same `soarm_sdk.RobotInterface` real hardware uses. In progress. |
| [`SO-ARM100`](SO-ARM100/) | The vendored hardware repo — URDF/MJCF, CAD, BOM/assembly docs. Read-only. |

See `AGENTS.md` for the full layout, install order, and session-start protocol; `ARCHITECTURE.md` for how
the packages compose.

## Recent work

- **`soarm_sdk`:** calibration now tracks each servo's own EEPROM angle limits and refuses to connect on
  drift from what was last recorded, a dashboard tool to recentre a joint wrapped across the encoder's
  4095/0 wrap, and Save persists partial calibration progress instead of losing finished work to a
  restart.
- **`soarm_tamp`:** a safety preflight checks a manifest's waypoints against the servos' live EEPROM
  limits before streaming anything; a run aborts instead of drifting further behind when a joint falls
  too far behind the plan; the gripper no longer reopens itself on the segment after it closes; execution
  runs as a real subprocess so its timing isn't shared with the dashboard's GIL; and dashboard preview now
  plays back on an independent ghost mesh instead of fighting the live mirror.

Full detail on both is in each package's own `CHANGELOG.md`, and the TAMP work is broken down
step by step on the [project page](https://thanhndv212.github.io/soarm-ws-webpage/#tamp).

## Installation

```bash
git clone --recurse-submodules https://github.com/thanhndv212/soarm-ws.git
cd soarm-ws
```

Each package installs independently — `pip install -e .` is the default:

```bash
cd soarm_sdk && pip install -e .
cd ../imu_sdk && pip install -e .
cd ../m5teleop && pip install -e .
cd ../soarm_lerobot && pip install -e .
cd ../camera_calibration && pip install -e .
cd ../soarm_tamp && pip install -e .
```

`soarm_mjlab` uses [uv](https://docs.astral.sh/uv/) instead (`mjlab` gates `torch` behind mutually
exclusive CPU/CUDA extras plain pip can't express):

```bash
cd soarm_mjlab && make sync-cpu   # or: uv sync --extra cpu --group dev
```

`soarm_tamp` planning additionally needs its HPP container (`pyhpp` isn't pip-installable) — see
`soarm_tamp/README.md` for the container script and full plan/replay/execute workflow.

## License

MIT — see [`LICENSE`](LICENSE). Every first-party submodule carries its own MIT `LICENSE`; the vendored
`SO-ARM100` keeps its own.
