---
name: soarm-sdk
description: 'Work in soarm_sdk — the Feetech STS/SCS servo transport, RobotInterface abstraction, tick↔URDF calibration and Viser dashboard for the SO-ARM/SO-101. Use for reading or commanding joints, joint limits and safety clamps, servo discovery/IDs/EEPROM config, tick↔radian conversions, forward kinematics, trajectory resampling, or the soarm-dashboard CLIs. Also use whenever a joint angle looks wrong by a sign or a quarter turn. For the guided calibration procedure itself, use `calibrate`.'
---

# soarm_sdk — Servo Transport & Robot Interface

Path: `soarm_sdk/` · Package `soarm-sdk` v0.4.0 · hatchling, `src/` layout ·
Python ≥3.9 (looser than the rest of the workspace) · import `from soarm_sdk import ...`

This is the foundation: `m5teleop`, `soarm_tamp` and `soarm_mjlab` all reach
hardware through it. A change here is a change to every consumer — see
`soarm-workspace` for the bump-and-retest loop.

## Layer map — find the right layer before editing

```
protocol/   Feetech STS/SCS wire protocol: packet framing, checksums, register map
            (port_handler, packet_handler, group_sync_read/write, registers; sts/scscl
            are per-series wrappers). Knows nothing about a robot's joint layout.
bus/        Hardware access. discovery: port scan, servo diagnostics, raw write1/write2.
            servo_config: batch operation planning (OperationPlan, build_operation_plan,
            apply_plan) for ID reassignment, angle limits, accel/speed, torque, mode, baud.
            Backs soarm-reconfigure and the dashboard's Reconfigure tab.
robot/      THE ABSTRACTION BOUNDARY. interfaces.RobotInterface (structural Protocol)
            + the Robot ABC, with backends ServoRobot (real RS-485, via
            hardware.ServoHardwareInterface), NullRobot (in-memory), LeRobotRobot
            (lerobot SOFollower, optional extra). Joint limits and the per-step bound
            are enforced HERE, on every write, so they hold for every caller.
calibration/ tick ↔ URDF joint frame. frame (RobotCalibration, rezero_from_pose,
            seed_from_travel), pipeline (CalibrationPipeline, AcceptanceTolerances),
            limits (measured_is_trusted, effective_limits), sweep_cli (ROM sweep,
            the only remaining seeding path — offline seeding from a lerobot
            calibration file was removed).
conversions.py  The ONLY math boundary between ticks (0–4095) and SI (rad, rad/s).
kinematics/ URDF load + FK via yourdfpy, no viewer dependency (headless-safe).
trajectory.py   Waypoint resampling bounding per-joint step between commands.
dashboard/  Viser browser panels. GUI wiring only — logic lives in the layers above.
cli/        Console scripts. configs/  so101.yaml, soarm100.yaml. rate_limiter.py.
```

**Anything above `robot/` should speak `RobotInterface`, not a concrete backend.**
That contract is why a policy trained in `soarm_mjlab` and a plan from `soarm_tamp`
drive the same object teleop does.

## Console scripts (installed on `$PATH`)

| Command | Does | Hardware? |
|---|---|---|
| `soarm-reconfigure --device /dev/ttyUSB0 --scan-range 1-6 --ui` | Servo setup/EEPROM TUI | yes |
| `soarm-dashboard-setup --device /dev/cu.usbserial-XXXX` | Every tab: Start Up, Homing Wizard, Reconfigure, Command Panel, PID Tuning, Monitor, Recorder (7 tabs) | yes |
| `soarm-dashboard-calibration --device /dev/cu.usbmodemXXXX --stream` | The guided URDF-frame calibration and acceptance workflow. **Primary calibration entry point — see `calibrate`.** | yes |
| `soarm-calibrate-rom --arm-id <name>` | Standalone ROM sweep (`--dry-run` simulates); feeds the same ROM acceptance row the dashboard's Travel tab does | yes |
| `soarm-widen-limit` | Widen a declared joint limit that's clamping a trustworthy measured range | no |

`examples/*.py` (`reconfigure.py`, `calibrate_rom.py`, `setup_dashboard.py`,
`calibration_dashboard.py`) are thin launchers over these, for running from a
checkout: `python soarm_sdk/examples/reconfigure.py ...`.

## The calibration story — read before touching any angle

`calibration/` answers **"what tick value means zero radians to the URDF?"** It is
distinct from `bus/servo_config`, which configures servo registers. (These two swapped
meanings in the 2026-09 reorg — pre-reorg `soarm_sdk.calibration` meant EEPROM
configuration. That is the one rename **not** covered by a compatibility shim.)

**The validated procedure is reference-pose zeroing, not travel seeding.**
`rezero_from_pose()` pins a joint's zero from a named, physically-established
reference pose (e.g. `folded_flat` covers `shoulder_lift`/`elbow_flex`); this is what
`soarm-dashboard-calibration`'s guided workflow drives, and it is the one covered in
full by the **`calibrate`** skill — read that skill for the procedure, not this one.
`seed_from_travel()` (from `soarm-calibrate-rom`'s measured ROM endpoints — offline
seeding from a lerobot file was removed) still cannot recover direction signs or a
true zero on an asymmetric
mechanism — a travel-only seed on this arm's geometry produced spans off by a
`span_ratio` of 0.96–1.34, i.e. wrong. Treat it as a fallback for a first rough pass,
never as the final calibration.

A calibration is written `validated: false` until it passes the acceptance record
(signs, ROM, zero-source provenance, reference-pose repeatability). Consumers are
entitled to refuse to move on an unvalidated calibration — `soarm_tamp.execute` does
exactly that.

`ServoRobot` enforces a per-step clamp (`max_step_rad`) on every write, and
`calibration.limits.effective_limits` **replaces** a model's declared joint limits
with the accepted ROM travel (gated on `measured_is_trusted` — the ROM acceptance row
passing: repeated, non-simulated, within tolerance) rather than always intersecting
the two. Intersection alone kept the more conservative number even once the travel
was trustworthy, which once clamped a planned trajectory on 55% of its waypoints; an
untrusted sweep is still handled conservatively because it can be the *encoder's*
range on a wrapped joint, not the joint's.

**The recurring bug in this workspace is joint frames.** Three conventions are live —
raw ticks, lerobot normalized degrees, URDF kinematic zero. Declared joint limits were
in mixed frames until 2026-09 (two joints off by ±π/2), unnoticed until the SDK began
enforcing them and clamped 55% of a planned trajectory. **Whenever you write or review
a value in radians, state which frame it is in.** Never hard-code `4096`/`2048` —
go through `conversions.py`.

## Testing

```bash
cd soarm_sdk && hatch run test          # pytest tests
cd soarm_sdk && hatch run lint:check    # ruff check src tests
```

~20 test files, all hardware-free: they stop at the `PortHandler`/serial boundary
using fake port and packet-handler doubles (`FakeTxPortHandler`/`FakeRxPortHandler`,
`_FakePacketHandler`). Match that pattern — **no test may require a connected arm.**
Coverage spans conversions, protocol framing, bus, servo_config, robot/servo_robot/
null_robot/lerobot_robot, frame calibration, joint-limit frames, rom_sweep, trajectory,
gripper, torque, recentre, dashboard context, and both CLIs.

CI: `ruff check src tests` + `pytest`, matrixed Python 3.9–3.12, on push to main/master
and every PR. Ruff config is deliberately narrow (`select = ["E4","E7","E9","F"]`) —
don't widen it or mass-fix findings it never opted into.

## Conventions and traps

- **Deprecation shims:** every pre-reorg flat import path still resolves (it was a flat
  20-module namespace before 2026-09). Write new code against the layered paths; don't
  delete a shim without checking `soarm_tamp`, `m5teleop` and `soarm_mjlab`.
- Optional extras: `[viser]` (dashboard: viser, yourdfpy, trimesh) and `[lerobot]`
  (`LeRobotRobot`; nothing else imports lerobot and the import is deferred to
  `connect()` — keep it that way).
- The dashboard polls all joints per cycle with a single `GroupSyncRead`, falling back
  to per-servo reads on failure.
- Serial baud for the servo bus is **1000000** (the IMU's is 115200).
- The dashboards' FK defaults to `SO-ARM100/Simulation/SO101/so101_new_calib.urdf`,
  mapped through the arm's saved calibration (`~/.soarm_sdk/calibration.json` by
  default) — there is no live SO100 default left. Without a calibration file the view
  assumes tick 2048 is zero on every joint and will not match the arm.
- `soarm_sdk`'s README once documented a `fullstack_manip/core/hardware_interface.py`
  with a `MotionExecutor`. **That code has never existed here** and there is no
  `MotionExecutor` anywhere in the workspace. See root `archive/MIGRATION_PLAN.md`.
- Docs: `soarm_sdk/docs/usage.md`, `CHANGELOG.md` (read before `git log`).
