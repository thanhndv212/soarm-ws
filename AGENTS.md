# AGENTS.md

## Workspace overview

Five independent Python packages for the SO-ARM100 robot arm. **No root build tool** —
each package is installed and tested independently.

```
soarm-ws/
├── soarm_sdk/       # SDK for Feetech STS/SCS serial bus servos (hatchling, src layout)
├── imu_sdk/         # IMU reader for M5StickC Plus / ESP32+MPU over USB serial
├── m5teleop/        # IMU teleoperation pipeline (ESKF → orientation controller → IK)
├── camera_calibration/  # Camera calibration + ArUco detection (Rerun viz)
└── SO-ARM100/       # Hardware: STL, STEP, URDF, MuJoCo simulation (read-only assets)
```

- All packages require Python **≥3.10** (soarm_sdk: ≥3.9).
- `soarm_sdk` uses **hatchling** + `src/` layout. Imports are `from soarm_sdk import ...`.
- All others use **setuptools** + flat layout.

## Install

```bash
pip install -e soarm_sdk/
pip install -e soarm_sdk/[viser]    # with 3-D dashboard deps (viser, yourdfpy, trimesh)
pip install -e imu_sdk/
pip install -e camera_calibration/
pip install -e m5teleop/
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
