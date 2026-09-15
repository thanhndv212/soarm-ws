# AGENTS.md

## Session Start Protocol

At the start of every session, load project context:
```bash
python3 ~/.config/opencode/skills/brain/scripts/brain.py context /Users/thanhndv212/Develop/soarm-ws
```
This surfaces relevant facts, learnings, and open tasks from 365 past sessions. Use this knowledge to avoid repeating past mistakes and to build on established patterns.

## Workspace overview

Seven independent Python packages for the SO-ARM100/SO-101 robot arm, plus the
vendored hardware repo. **No root build tool** — each package is installed and
tested independently. Each package has its own GitHub remote; this repo uses
**git submodules** to track them together. The whole workspace is MIT-licensed;
every submodule (except the vendored `SO-ARM100`, which carries its own) has its
own `LICENSE` and `CHANGELOG.md` — check a package's `CHANGELOG.md` before
`git log`-spelunking it for recent changes.

```
soarm-ws/              ← this repo (root, tracks submodule commits)
├── soarm_sdk/         ← git submodule → github.com/thanhndv212/soarm_sdk
├── imu_sdk/           ← git submodule → github.com/thanhndv212/imu_sdk
├── m5teleop/          ← git submodule → github.com/thanhndv212/m5teleop
├── camera_calibration/← git submodule → github.com/thanhndv212/camera_calibration
├── soarm_lerobot/     ← git submodule → github.com/thanhndv212/soarm_lerobot
├── soarm_mjlab/       ← git submodule → github.com/thanhndv212/soarm_mjlab
├── soarm_tamp/        ← git submodule → github.com/thanhndv212/soarm_tamp
├── SO-ARM100/         ← git submodule → github.com/TheRobotStudio/SO-ARM100 (read-only)
├── archive/           ← completed plan docs, kept for history (not submodules)
└── docs/images/       ← screenshots referenced by README.md (not submodules)
```

- All packages require Python **≥3.10** (soarm_sdk: ≥3.9; soarm_tamp: ≥3.11).
- **`m5teleop` now depends on `soarm_sdk`** (for the arm transport). Install
  the SDK first, or `pip install -e m5teleop/` will pull it from PyPI rather
  than using this checkout.
- `soarm_sdk` uses **hatchling** + `src/` layout. Imports are `from soarm_sdk import ...`.
- `soarm_tamp` also uses **hatchling**, but flat layout (`soarm_tamp/soarm_tamp/`).
- Everything else (`imu_sdk`, `m5teleop`, `camera_calibration`, `soarm_lerobot`,
  `soarm_mjlab`) uses **setuptools** + flat layout.
- `soarm_mjlab` is the one package installed with **uv**, not pip — see Install below.

**SO-100 vs SO-101 naming trap:** the vendored `SO-ARM100/Simulation/` ships URDF
for *both* hardware revisions — `SO100/so100.urdf` and `SO101/so101_new_calib.urdf`.
The physical arm in this workspace is an **SO-101**. `soarm_sdk`'s viser dashboard
now points at `SO101/so101_new_calib.urdf` too; `soarm_tamp` and `soarm_mjlab` both
correctly vendor/reference the SO101 revision, and `soarm_sdk` now ships a
`configs/so101.yaml` (which `soarm_tamp` loads explicitly). When adding real-arm
code, default to the SO101 URDF/MJCF and config unless you're specifically
touching that dashboard.

**Joint frames are the recurring bug in this workspace.** Three conventions are
live — raw servo ticks, lerobot's normalized degrees, and the URDF's kinematic
zero — and they have been silently conflated more than once. `soarm_sdk`'s
declared joint limits were in mixed frames until 2026-09 (two joints offset by
±π/2), which went unnoticed until the SDK began enforcing them and clamped 55%
of a planned trajectory. When you touch anything expressed in radians, say which
frame it is in. `soarm_sdk.calibration.frame` is the only thing that relates
ticks to the URDF, and `ServoRobot` intersects declared limits with the arm's
measured travel so the physical stops always win.

## Git workflow (submodules)

### Clone
```bash
git clone --recurse-submodules <this-repo-url>
```

### Update all submodules to latest remote
```bash
git submodule update --remote --recursive
```

### Cross-repo status
```bash
git submodule foreach 'echo "--- $name ---" && git status -sb'
```

### Cross-repo pull
```bash
git submodule foreach git pull
```

### Make a change in a submodule
```bash
cd <submodule>
git checkout -b my-feature
# ... edit, commit ...
git push origin my-feature
cd ..
git add <submodule>            # bump the submodule pointer
git commit -m "bump <submodule> for <reason>"
```

### Principle
- **Submodules are pinned at specific commits** in this repo. You control when to bump.
- `SO-ARM100` is read-only hardware from TheRobotStudio — don't push changes to it.
- Treat cross-package changes as: bump submodule → re-install → test.

## Install

```bash
pip install -e soarm_sdk/
pip install -e soarm_sdk/[viser]    # with 3-D dashboard deps (viser, yourdfpy, trimesh)
pip install -e imu_sdk/
pip install -e camera_calibration/
pip install -e m5teleop/
pip install -e soarm_lerobot/
pip install -e soarm_tamp/[host]    # host side (execute.py) — pulls in soarm_sdk
```

There is **no root pyproject.toml or requirements.txt**. Install each package explicitly.

`soarm_tamp`'s planning half (`plan.py`, `replay.py`) needs `long_tamp` + `pyhpp`,
which only exist inside its HPP Docker container (`soarm_tamp/scripts/hpp_container.sh`)
— don't try to `pip install` those on the host. See "soarm_tamp" under Architecture
notes below.

```bash
cd soarm_mjlab && make sync-cpu   # dev machine, no GPU (or: uv sync --extra cpu --group dev)
cd soarm_mjlab && make sync       # GPU training box, CUDA 12.8 (or: uv sync --extra cu128 --group dev)
```

`soarm_mjlab` uses **uv**, not pip — `mjlab` gates `torch` behind mutually-exclusive
CPU/CUDA extras that pip can't route cleanly. `uv.lock` is committed and CI runs
`uv sync --locked`, so a stale lockfile fails the build.

## Key commands

### Lint
```bash
cd soarm_sdk && hatch run lint:check   # ruff check src tests
cd soarm_mjlab && make lint            # uv run ruff check soarm_mjlab tests
```

### Test
```bash
cd soarm_sdk && hatch run test         # pytest tests
cd camera_calibration && pytest tests/ -v
cd soarm_mjlab && make test            # uv run pytest (make test-cpu forces FORCE_CPU=1)
```
`soarm_sdk`, `camera_calibration`, `soarm_mjlab` and `m5teleop` have tests
(`cd m5teleop && pytest tests/ -v` — its suite runs on the `--dry-run` path,
so it needs no hardware, no lerobot and no pinocchio); `soarm_sdk` and
`soarm_mjlab` both have CI (see Code style below). `imu_sdk`,
`soarm_lerobot`, `soarm_tamp` have none.

### Run (hardware required unless noted)

| What | Command |
|------|---------|
| Servo calibration UI | `soarm-calibrate --device /dev/ttyUSB0 --scan-range 1-6 --ui` (console script; `python soarm_sdk/examples/calibrate.py bus ...` from a checkout) |
| Servo dashboard (browser) | `soarm-dashboard --device /dev/cu.usbserial-XXXX` (setup-only tabs: `soarm-dashboard-setup`) |
| Measure + save a URDF-frame calibration (hardware) | `soarm-calibrate-rom --arm-id <name>` (ROM sweep -> `seed_from_travel` -> `~/.soarm_sdk/calibration.json`; `--dry-run` simulates it; `python soarm_sdk/examples/calibrate.py rom ...` from a checkout) |
| Seed a URDF-frame calibration (no hardware) | `soarm-seed-calibration --lerobot <lerobot.json>` |
| Camera calibration CLI | `camera-calibration capture --images 20` (installed console script) |
| Teleop (dry-run, no hardware) | `cd m5teleop && python teleop.py --dry-run` |
| Teleop (full) | `cd m5teleop && python teleop.py --servo-port /dev/cu.usbserial-XXXX` |
| Teleop + record dataset | `cd m5teleop && python teleop.py --servo-port /dev/cu.usbserial-XXXX --record` |
| EKF tuning (stationary rec) | `cd m5teleop && python tune_ekf.py stationary --duration 90 --save rec.npz` |
| EKF tuning (offline sweep) | `cd m5teleop && python tune_ekf.py sweep --load rec.npz` |
| TAMP: plan (container) | `cd soarm_tamp && ./scripts/hpp_container.sh plan --out runs/cube01 --viewer none` |
| TAMP: replay in 3-D viewer (no hardware) | `cd soarm_tamp && ./scripts/hpp_container.sh replay --run runs/cube01` (viser on :8000) |
| TAMP: dry-run what would stream (no hardware) | `cd soarm_tamp && python -m soarm_tamp.execute runs/cube01 --dry-run` |
| TAMP: execute on hardware | `cd soarm_tamp && python -m soarm_tamp.execute runs/cube01 --port /dev/cu.usbmodemXXXX` |
| RL: train Reach policy (sim only) | `cd soarm_mjlab && uv run python scripts/train.py SoArm100-Reach` |
| RL: play a trained checkpoint (sim only) | `cd soarm_mjlab && uv run python scripts/play.py ...` (see `soarm_mjlab/README.md`) |

### Firmware (Arduino IDE required)
Flash before using IMU:
- **M5StickC Plus 1.1**: `imu_sdk/firmware/m5imu_firmware/m5imu_firmware.ino`
- **ESP32 + MPU**: `imu_sdk/firmware/esp32_mpu/esp32_mpu.ino`

## Dependencies that break without special setup

- **pinocchio** — install via conda, not pip: `conda install -c conda-forge pinocchio` (m5teleop hard-depends on it)
- **quadprog** — C extension, may need `brew install gfortran` on macOS
- The author's env is called `gosim` (conda).
- **`long_tamp` / `pyhpp`** (soarm_tamp planning half) — only importable inside the
  HPP Docker container spun up by `soarm_tamp/scripts/hpp_container.sh`; not pip-installable
  on the host. See the sibling `long-tamp` repo in `agimus-ws` for what's inside that container.
- **`uv`** (soarm_mjlab) — required, not optional; plain `pip install -e .` won't route the
  CPU/CUDA `torch` extras correctly. Install via `curl -LsSf https://astral.sh/uv/install.sh | sh`
  or see [astral.sh/uv](https://docs.astral.sh/uv/).

## Architecture notes

- **Teleop pipeline**: `teleop.py` runs a 50 Hz real-time loop: IMU data → Error-State Kalman Filter (`imu_ekf.py`) → cascade P-P quaternion orientation controller (`orient_controller.py`) → differential IK via pink+pinocchio (`ik_solver.py`) → servo commands via `ArmInterface` (`lerobot_soarm_interface.py`), which since 2026-09 delegates to `soarm_sdk.LeRobotRobot` (hardware, lerobot `SOFollower` underneath) or `soarm_sdk.NullRobot` (`--dry-run`). Both satisfy `soarm_sdk.RobotInterface`, so teleop's arm is the same kind of object TAMP and RL drive.
- **Dataset recording**: `--record` flag on `teleop.py` integrates `soarm_lerobot.TeleopRecorder`, which buffers frames and saves episodes as a LeRobotDataset. Episodes are delimited by BTN_A press (teleop on/off). Training data flows through `soarm_lerobot/dataset.py` (chunking, normalisation) into ACT or Diffusion Policy training.
- **Simulation** runs in parallel with hardware: Viser 3-D browser viewer (`sim_interface.py`) and Rerun data logger (`viz.py`).
- `SO-ARM100/Simulation/` has URDF files and MuJoCo MJCF (`scene.xml`) for physics sim.
- Buttons on M5StickC: BTN_A toggles teleop, BTN_B toggles gripper.
- Serial baud: 115200 for IMU, 1000000 for servo bus.
- **`soarm_sdk` is organized in layers, one subpackage each:** `protocol/`
  (Feetech wire protocol) → `bus/` (discovery, diagnostics, servo EEPROM
  config) → `robot/` (the `RobotInterface`/`Robot` abstraction + `ServoRobot`
  / `NullRobot` backends), alongside `calibration/` (tick ↔ URDF frame),
  `kinematics/`, `trajectory.py`, `dashboard/` and `cli/`. It was a flat
  20-module namespace until the 2026-09 reorg; **every pre-reorg import path
  still works via deprecation shims**, so nothing downstream had to change.
  The one exception: `soarm_sdk.calibration` used to mean servo EEPROM
  configuration and now means the URDF-frame mapping — that code moved to
  `soarm_sdk.bus.servo_config`. See `soarm_sdk/CHANGELOG.md`.
- **`soarm_sdk`'s calibration/safety layer is what `soarm_tamp` and
  `soarm_mjlab` both build on.** `calibration/frame.py` maps raw servo ticks
  to the URDF's joint frame (`RobotCalibration`, seeded offline via
  `seed_from_travel()`/`calibration/seed.py`, marked `validated: false` until
  a physical direction-sign check passes). `ServoRobot`/`RobotInterface` now
  enforce declared joint limits and a per-step clamp (`max_step_rad`) on
  every write, not just protocol-range clamping. This is the shared "same
  interface for sim and hardware" contract both newer packages depend on.
- **`soarm_tamp` — long-horizon TAMP, planning and execution in separate processes.**
  `plan.py`/`replay.py` run inside the HPP container (`long_tamp` + `pyhpp`, ported
  from the `long-tamp`/`agimus_spacelab` planning stack — see `agimus-ws`); `execute.py`
  runs on the host against `soarm_sdk`. The two never share an interpreter — the
  contract between them is a waypoint manifest on disk: `plan (container) → runs/<name>/manifest.json
  → execute (host)`. Joint-angle zero differs between the planning URDF, `soarm_sdk`,
  and lerobot; the mapping lives in `soarm_sdk.calibration.frame`, is seeded offline
  from measured travel, and `execute.py` **refuses to stream** until
  `validate_calibration.py` confirms the direction signs on the real arm. Uses the
  SO101 URDF revision (see the naming note above). Full task-specific detail (cube
  geometry, 5-DOF grasp mask, growing the scene) is in `soarm_tamp/README.md`.
- **`soarm_mjlab` — RL training deployed through the same interface hardware uses.**
  Trains policies for SO-ARM100 in MuJoCo via `mjlab`, deployed through
  `soarm_sdk.RobotInterface` — the same interface real-hardware teleop code uses, so
  a trained policy doesn't distinguish sim from the physical arm. Vendors the SO101
  MJCF/meshes directly into the package (no cross-submodule file references at
  runtime) and mirrors `soarm_sdk`'s joint names/home-pose config 1:1. Progress and
  training campaign results are tracked in `SOARM_MJLAB_ROADMAP.md`.

## Code style

- Ruff for linting (soarm_sdk pins `[tool.ruff.lint] select = ["E4","E7","E9","F"]`
  in its `pyproject.toml` — ruff's own defaults have drifted much wider than that
  over versions, so an unpinned `ruff check` reports hundreds of style findings
  this workspace never opted into; run `ruff check` in other packages too, but
  read the output with that in mind).
- No pre-commit hooks at the workspace level.
- Two packages have CI. `soarm_mjlab` (`.github/workflows/ci.yml`): a `fast` job
  (lint + full CPU test pyramid) blocks merges on every push/PR; a non-blocking
  `train-smoke` job runs a longer PPO slice post-merge/on release and uploads the
  checkpoint as a build artifact. `soarm_sdk` (`.github/workflows/ci.yml`):
  `ruff check src tests` + `pytest`, matrixed over Python 3.9–3.12, on push to
  main/master and on every PR.
- Single author repo — no branch conventions documented

## Related docs

- `README.md` — workspace overview, package table, recent-work summary, dashboard screenshots
  (pending — see `docs/images/README.md`), and a link to the project webpage
- `ARCHITECTURE.md` — how the packages fit together, dependency graph, per-package details
- `CHANGELOG.md` — workspace-level changelog (each submodule also has its own)
- `SOARM_MJLAB_ROADMAP.md` — standing plan for ongoing RL-training work (active; Phase 4)
- `archive/` — completed plan docs, kept for history: `MIGRATION_PLAN.md` (Part A done,
  Part B deliberately gated) and `TELEMETRY_PLAN.md` (all five phases implemented)
- `m5teleop/IMPLEMENTATION.md` — full architecture, tuning guide, phase-by-phase build log (476 lines)
- `soarm_sdk/docs/usage.md` — servo SDK usage guide
- `soarm_tamp/README.md` — TAMP task setup, joint-calibration caveats, plan/execute workflow
- `soarm_mjlab/README.md` + `soarm_mjlab/docs/` — RL training setup, vast.ai GPU training guide, tuning debug log
- Each package has its own README (and now its own LICENSE + CHANGELOG.md)
