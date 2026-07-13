# AGENTS.md

## Session Start Protocol

At the start of every session, load project context:
```bash
python3 ~/.config/opencode/skills/brain/scripts/brain.py context /Users/thanhndv212/Develop/soarm-ws
```
This surfaces relevant facts, learnings, and open tasks from 365 past sessions. Use this knowledge to avoid repeating past mistakes and to build on established patterns.

## Workspace overview

Five independent Python packages for the SO-ARM100 robot arm. **No root build tool** —
each package is installed and tested independently. Each package has its own GitHub
remote; this repo uses **git submodules** to track them together.

```
soarm-ws/              ← this repo (root, tracks submodule commits)
├── soarm_sdk/         ← git submodule → github.com/thanhndv212/soarm_sdk
├── imu_sdk/           ← git submodule → github.com/thanhndv212/imu_sdk
├── m5teleop/          ← git submodule → github.com/thanhndv212/m5teleop
├── camera_calibration/← git submodule → github.com/thanhndv212/camera_calibration
├── soarm_learn/       ← git submodule → github.com/thanhndv212/soarm_learn
└── SO-ARM100/         ← git submodule → github.com/TheRobotStudio/SO-ARM100
```

- All packages require Python **≥3.10** (soarm_sdk: ≥3.9).
- `soarm_sdk` uses **hatchling** + `src/` layout. Imports are `from soarm_sdk import ...`.
- All others use **setuptools** + flat layout.

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
pip install -e soarm_learn/
```

There is **no root pyproject.toml or requirements.txt**. Install each package explicitly.

## Key commands

### Lint
```bash
cd soarm_sdk && ruff check src       # (hatch env lint)
```

### Test
```bash
cd camera_calibration && pytest tests/ -v
```
Only `camera_calibration` has tests. Other packages have none.

### Run (hardware required unless noted)

| What | Command |
|------|---------|
| Servo calibration UI | `python soarm_sdk/examples/calibrate.py --device /dev/ttyUSB0 --scan-range 1-6 --ui` |
| Servo dashboard (browser) | `python soarm_sdk/examples/viser_dashboard.py --device /dev/cu.usbserial-XXXX` |
| Camera calibration CLI | `camera-calibration capture --images 20` (installed console script) |
| Teleop (dry-run, no hardware) | `cd m5teleop && python teleop.py --dry-run` |
| Teleop (full) | `cd m5teleop && python teleop.py --servo-port /dev/cu.usbserial-XXXX` |
| Teleop + record dataset | `cd m5teleop && python teleop.py --servo-port /dev/cu.usbserial-XXXX --record` |
| EKF tuning (stationary rec) | `cd m5teleop && python tune_ekf.py stationary --duration 90 --save rec.npz` |
| EKF tuning (offline sweep) | `cd m5teleop && python tune_ekf.py sweep --load rec.npz` |

### Firmware (Arduino IDE required)
Flash before using IMU:
- **M5StickC Plus 1.1**: `imu_sdk/firmware/m5imu_firmware/m5imu_firmware.ino`
- **ESP32 + MPU**: `imu_sdk/firmware/esp32_mpu/esp32_mpu.ino`

## Dependencies that break without special setup

- **pinocchio** — install via conda, not pip: `conda install -c conda-forge pinocchio` (m5teleop hard-depends on it)
- **quadprog** — C extension, may need `brew install gfortran` on macOS
- The author's env is called `gosim` (conda).

## Architecture notes

- **Teleop pipeline**: `teleop.py` runs a 50 Hz real-time loop: IMU data → Error-State Kalman Filter (`imu_ekf.py`) → cascade P-P quaternion orientation controller (`orient_controller.py`) → differential IK via pink+pinocchio (`ik_solver.py`) → servo commands via lerobot SOFollower (`lerobot_soarm_interface.py`).
- **Dataset recording**: `--record` flag on `teleop.py` integrates `soarm_learn.TeleopRecorder`, which buffers frames and saves episodes as a LeRobotDataset. Episodes are delimited by BTN_A press (teleop on/off). Training data flows through `soarm_learn/dataset.py` (chunking, normalisation) into ACT or Diffusion Policy training.
- **Simulation** runs in parallel with hardware: Viser 3-D browser viewer (`sim_interface.py`) and Rerun data logger (`viz.py`).
- `SO-ARM100/Simulation/` has URDF files and MuJoCo MJCF (`scene.xml`) for physics sim.
- Buttons on M5StickC: BTN_A toggles teleop, BTN_B toggles gripper.
- Serial baud: 115200 for IMU, 1000000 for servo bus.

## Code style

- Ruff for linting (soarm_sdk has config; run `ruff check` in other packages too)
- No pre-commit hooks, no CI
- Single author repo — no branch conventions documented

## Related docs

- `m5teleop/IMPLEMENTATION.md` — full architecture, tuning guide, phase-by-phase build log (476 lines)
- `soarm_sdk/docs/usage.md` — servo SDK usage guide
- Each package has its own README
