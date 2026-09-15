---
name: soarm-imu-sdk
description: 'Work in imu_sdk — the serial IMU reader and Arduino firmware (M5StickC Plus 1.1 / ESP32 + MPU6050/6500/9250) that feeds SO-ARM teleoperation. Use for reading IMU samples, ImuReader/ImuData/find_port, port auto-detection, flashing or editing firmware, gyro bias calibration, choosing 6-axis vs 9-axis, or when the IMU stream is empty, garbled, or the port will not open.'
---

# imu_sdk — IMU Transport & Firmware

Path: `imu_sdk/` · v0.2.0 · setuptools, flat layout · Python ≥3.10 · one dependency
(`pyserial`) · import `from imu_sdk import ...`

Pairs Arduino firmware with a Python reader. `m5teleop` is its only consumer, and the
**only package in the workspace that imports another workspace package directly**
(`from imu_sdk import ImuData, ImuReader, find_port`). Everything else is glued at the
process/CLI level.

## The two halves

### Python (`imu_sdk/`)

- `imu_data.py` — the `ImuData` dataclass. **`pitch`/`roll`/`yaw` exist but are always
  `0.0` coming from firmware.** Orientation is computed on the *host*, by `m5teleop`'s
  Error-State Kalman Filter — never on the device. Do not add device-side fusion to
  make these fields non-zero without going through `soarm-m5teleop` first; the ESKF
  expects raw rates and accelerations.
- `reader.py` — `ImuReader`, in three usage modes: synchronous iteration, single
  `read_one()`, or callback on a background thread via `.start()`. Plus `find_port()`
  for auto-detection. The reader **silently filters non-data packets** (boot,
  calibration and error lines), so only valid `ImuData` ever surfaces to a caller —
  which is exactly why a firmware problem looks like *silence* on the Python side, not
  an exception. When debugging an empty stream, read the raw port first.

### Firmware (`imu_sdk/firmware/`, Arduino IDE required)

| Sketch | Target |
|---|---|
| `m5imu_firmware/m5imu_firmware.ino` | M5StickC Plus 1.1 (MPU6886, 6-axis) |
| `esp32_mpu/esp32_mpu.ino` | Generic ESP32 + MPU6050/6500 (6-axis) or MPU9250/9265+AK8963 (9-axis) — selected by a **`#define` at the top of the file** |

Both variants:
- Stream **JSON lines at ~100 Hz over 115200-baud USB serial** (the servo bus is
  1000000 — different number, easy to cross).
- Perform **gyro bias calibration at boot**: 500 samples, ~2.5 s, **the device must be
  held still**, then the bias is subtracted from every subsequent sample. A drifting
  or offset stream almost always means the device moved during boot — power-cycle it
  flat on the desk before blaming the filter.

Flash the firmware before first use, and re-flash after editing the `#define`.

## Buttons (M5StickC, consumed by `m5teleop`)

`BTN_A` toggles teleop on/off (and delimits recorded episodes), `BTN_B` toggles the
gripper. Firmware reports them in the JSON stream; the semantics live in
`m5teleop/teleop.py`.

## Testing and hygiene

**No test suite.** `test_buttons.py` sits at the repo root and is a hardware
smoke script, not pytest. Lint with `ruff check` (see the ruff caveat in
`soarm-workspace` — defaults are wider than this workspace opted into).

Traps:
- The build artifact directory is `m5imu.egg-info` — the package was renamed from
  `m5imu` and stale egg-info can shadow imports. Delete it if `import imu_sdk` resolves
  somewhere unexpected.
- Relicensed Apache-2.0 → MIT (whole workspace is MIT now).
- Changelog: `imu_sdk/CHANGELOG.md`. Read it before `git log`.
