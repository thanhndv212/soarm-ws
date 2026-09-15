---
name: soarm-m5teleop
description: 'Work in m5teleop — the 50 Hz IMU teleoperation loop that drives the SO-ARM/SO-101 (ESKF orientation → quaternion controller → differential IK via pink/pinocchio → soarm_sdk). Use for running or debugging teleop, tuning the EKF, orientation or IK behaviour, jitter/lag/drift in the arm, the viser sim window or Rerun logging, dry-run testing without hardware, or recording demonstrations with --record.'
---

# m5teleop — Teleoperation Pipeline

Path: `m5teleop/` · v0.1.0 · setuptools, flat layout · Python ≥3.10

**The integration point of the workspace** — where IMU, servos, simulation and dataset
recording meet. It is also the only package that imports another workspace package
directly (`imu_sdk`).

## The 50 Hz loop

```
IMU (imu_sdk.ImuReader)
  → imu_ekf.py          Error-State Kalman Filter  → orientation
  → orient_controller.py cascade P-P quaternion controller → angular velocity
  → ik_solver.py         differential IK (pink + pinocchio) → joint targets
  → lerobot_soarm_interface.py (ArmInterface) → servos
```

`ArmInterface` used to wrap lerobot's `SOFollower` directly; since 2026-09 it delegates
to `soarm_sdk.LeRobotRobot` (hardware) or `soarm_sdk.NullRobot` (`--dry-run`). Both
satisfy `soarm_sdk.RobotInterface`, **so teleop's arm is the same kind of object TAMP
and RL drive** — keep it that way; don't reach past the interface to a backend.

Supporting modules: `lpf.py` (low-pass filtering), `imu_twist.py`, `config.py`
(`CONTROL_HZ` and friends), `sim_interface.py` (Viser 3-D window, runs *in parallel*
with hardware), `viz.py` (Rerun data logging).

Buttons: **BTN_A toggles teleop** (and delimits recorded episodes), **BTN_B toggles the
gripper**.

## Running it

```bash
cd m5teleop
python teleop.py --dry-run                                  # no hardware at all
python teleop.py --servo-port /dev/cu.usbserial-XXXX        # full
python teleop.py --servo-port /dev/cu.usbserial-XXXX --record   # + dataset
```

Flags: `--imu-port` (auto-detected if omitted), `--servo-port`, `--dry-run`,
`--no-sim` (kill the viser window), `--no-rerun`, `--no-rerun-spawn` (log without
launching the viewer), `--hz` (default `config.CONTROL_HZ` = 50), and the recording
set `--record`, `--record-repo-id` (default `thanhndv212/soarm100-teleop-v1`),
`--record-root`, `--record-task`, `--record-fps` (default 50).

**`--dry-run` is the bisect point.** It disables serial and runs the IK offline. If
behaviour is wrong there, the bug is in the filter/controller/IK; if only the live run
is wrong, it is transport, calibration frames, or the arm.

## EKF tuning

```bash
python tune_ekf.py stationary --duration 90 --save rec.npz   # record a still trace
python tune_ekf.py sweep --load rec.npz                      # offline parameter sweep
```

Record stationary first, sweep offline second — never tune against a live arm. Note the
firmware already does gyro bias calibration at boot (device must be still); apparent
drift is usually that, not a filter gain. See `soarm-imu-sdk`.

## Recording demonstrations

`--record` pulls in `soarm_lerobot.TeleopRecorder`, which buffers frames and saves
episodes as a `LeRobotDataset`, with episodes delimited by BTN_A. The import in
`teleop.py` is wrapped in `try/except ImportError` — **recording is an optional add-on,
not a hard dependency.** Preserve that. Dataset handling and training belong to
`soarm-lerobot`.

## Testing

```bash
cd m5teleop && pytest tests/ -v
```

`tests/test_arm_interface.py` exercises the `--dry-run` path, so the suite needs **no
hardware, no lerobot and no pinocchio**. Keep new tests on that path — a test that
imports pinocchio makes the suite unrunnable on a plain pip environment.

## Traps

- **pinocchio must come from conda** (`conda install -c conda-forge pinocchio`); it is a
  hard dependency here. `quadprog` may need `brew install gfortran` on macOS. The
  author's env is `gosim`.
- Full dependency set: `soarm_sdk`, `pin-pink`, `quadprog`, `pinocchio`, `viser`,
  `rerun-sdk`, `numpy`, `pyserial`, `loop-rate-limiters`.
- **Install `soarm_sdk` from this checkout first**, or `pip install -e m5teleop/` pulls
  the PyPI copy instead.
- IMU serial is 115200 baud; the servo bus is 1000000.
- FK/URDF for the viser window comes from `SO-ARM100/`; the physical arm is an
  **SO-101** — see the SO100/SO101 rule in `soarm-start`.
- **`m5teleop/IMPLEMENTATION.md` (476 lines) is the real reference**: full
  architecture, tuning guide, and a phase-by-phase build log. Read it before
  substantive changes to the filter or controller. Also `CHANGELOG.md`.
