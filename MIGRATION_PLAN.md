# soarm_sdk Upgrade Plan & fullstack_manip Migration

**Status (2026-07-13): Part A implemented, plus a scoped slice of Part B
un-gated by a clarified vision (see "Part A+" below).** Changes are committed
and pushed to feature branches in both repos, not yet merged and not yet
reflected in `soarm-ws`'s pinned `soarm_sdk` submodule commit:
- `soarm_sdk` branch [`sdk-hardening`](https://github.com/thanhndv212/soarm_sdk/tree/sdk-hardening) (A1–A3)
- `fullstack-manip` branch [`resolve-soarm-sdk-fork`](https://github.com/thanhndv212/fullstack-manip/tree/resolve-soarm-sdk-fork) (A4)
- `soarm_sdk` branch [`add-robot-interface`](https://github.com/thanhndv212/soarm_sdk/tree/add-robot-interface) (Part A+)

The rest of Part B remains gated/unscheduled as designed.

---

Revised 2026-07-13 after critique of the first draft: that draft was a code-mover's
plan (a 30-file mapping table with mechanical rename instructions) that never asked
whether the code should move yet. It also proposed folding a whole algorithms stack
into a hardware driver, and then — one step better but still premature — proposed
standing up a new versioned package for code nothing currently calls.

Revised position, in priority order:

1. ✅ **Done.** `soarm_sdk` needs to become an actual product-grade SDK first. It had zero
   tests, no CI, no `py.typed`, no `LICENSE` file, and was stuck at `0.1.0` through
   10+ commits including breaking renames. This matters more than any repackaging
   and is independent of fullstack_manip entirely.
2. ✅ **Done.** Resolve the `soarm_sdk` / `stservo-sdk` fork now. Two byte-identical copies
   of checksum/packet-framing code for the same hardware would have drifted silently.
3. **Do not migrate fullstack_manip's kinematics/planning/control/recording/analysis
   stack speculatively.** None of it has been exercised against real SO-ARM100
   hardware — its own examples run via `mjpython` against MuJoCo, not
   `--backend real`. `m5teleop` already has a hardware-validated IK and control
   loop; migrating well-organized-but-unused code just gives it a professional
   home it hasn't earned. Migrate pieces individually, only when a concrete
   real-hardware task needs them.

---

## Part A — `soarm_sdk` upgrade (do this now, regardless of fullstack_manip)

### A1. Test suite — ✅ Done

`soarm_sdk` has no `tests/` directory at all. Most of the package talks to real
serial hardware, so tests need to stop at the `PortHandler`/serial boundary rather
than requiring a connected arm:

| Test file | Covers | Needs hardware? |
|---|---|---|
| `tests/test_conversions.py` | `ticks_to_radians`/`radians_to_ticks`/speed conversions/batch joint conversions | No — pure math, currently completely unverified |
| `tests/test_protocol_packet_handler.py` | Packet framing + checksum computation | No — pure byte-fixture tests |
| `tests/test_calibration.py` | `OperationPlan`, `build_operation_plan`, `parse_range`, `parse_mapping` | No — pure planning logic |
| `tests/test_bus.py` | `discover_servos`/`scan_servos`/`read_diagnostics` control flow | No — mock `serial.Serial` / `serial.tools.list_ports` |

**Landed as:** exactly these 4 files, 71 tests, all passing against fake
port/packet-handler doubles (`FakeTxPortHandler`/`FakeRxPortHandler` in
`test_protocol_packet_handler.py`, a `_FakePacketHandler` in `test_bus.py`).
`discover_servos`/`read_diagnostics` themselves weren't unit-tested directly —
they're thin open/close wrappers around `scan_servos`, which is; opening a real
`serial.Serial` wasn't worth mocking for the marginal coverage gained.
One real finding along the way: `ProtocolPacketHandler.txPacket()` deliberately
leaves `is_using=True` on success — the bus is only released by the paired
`rxPacket()` call at the end of a full round trip, not by the transmit side
alone. Not a bug; documented via the test's comment so it doesn't look like one
next time someone reads it.

`[tool.hatch.envs.default.scripts]` now has `test = "pytest {args:tests}"`, and
`[tool.pytest.ini_options] testpaths = ["tests"]` means plain `pytest` works
from the package root.

### A2. CI — ✅ Done

Add `soarm_sdk/.github/workflows/ci.yml`: run `ruff check src` (the `lint` hatch
env already exists and is unused) and `pytest` on push/PR, matrixed over Python
3.9–3.12 to match the classifiers already declared in `pyproject.toml`. This is
the single highest-leverage change here — the package currently claims support
for four Python versions with zero automated verification of any of them.

**Landed as:** `.github/workflows/ci.yml`, lint+test matrixed over 3.9–3.12.
Lint scope widened slightly from the original plan to `ruff check src tests` so
the new test suite is linted too. Fixed 3 pre-existing dead-import errors in
`calibration.py` (`Iterable`, `discover_servos`, `COMM_SUCCESS`) that `ruff
check src` was already flagging — CI would have been red on its first run
otherwise.

### A3. Packaging hygiene — ✅ Done

- Add `src/soarm_sdk/py.typed` and declare it in `tool.hatch.build.targets.wheel`
  package-data, so consumers get real type checking instead of `Any` everywhere.
- Add `LICENSE` (MIT) at the repo root — `pyproject.toml` declares
  `license = {text = "MIT"}` but there is no `LICENSE` file. A real gap if this
  is ever actually published to PyPI, as the README's `pip install soarm-sdk`
  instructions imply.
- Add `CHANGELOG.md` (Keep a Changelog format) and start bumping semver for real.
  `0.1.0` across a history that includes a public rename
  (`homing_calibrate.py` → `calibrate.py`) means nothing downstream can trust a
  version pin today.

**Landed as:** all three, plus one extra fix surfaced while doing this —
`pyproject.toml`'s `[project.urls]` pointed at `fullstack-manip` (this
package's origin before the split) instead of its own repo; corrected to
`github.com/thanhndv212/soarm_sdk`. Confirmed `py.typed` actually ships by
building the wheel and inspecting its contents (`hatchling` includes it
automatically since it's already inside `packages = ["src/soarm_sdk"]` — no
extra `force-include` needed, despite that being the first instinct).

### A4. Resolve the `soarm_sdk` / `stservo-sdk` fork — ✅ Done

`fullstack-manip/stservo-sdk/src/stservo_sdk/*` and `soarm_sdk/src/soarm_sdk/*`
are byte-identical forks of the protocol layer (`protocol_packet_handler.py`,
`sts.py`, `conversions.py`, etc. — confirmed via `diff`, zero differences).
`soarm_sdk` is a strict superset (`+bus.py`, `+calibration.py`). This will drift
silently the next time either gets a bug fix.

Fix: make `fullstack-manip` depend on `soarm_sdk` instead of vendoring its own copy.

1. In `fullstack-manip/pyproject.toml`, drop the local `stservo-sdk/` package;
   add `soarm-sdk` as a dependency (git dependency pointing at the `soarm_sdk`
   repo for now, PyPI once A1–A3 are done and it's actually published).
2. Delete `fullstack-manip/stservo-sdk/` entirely.
3. In `fullstack_manip/core/hardware_interface.py` (and any other file importing
   `stservo_sdk`), change `from stservo_sdk import ...` /
   `from stservo_sdk.conversions import ...` / `from stservo_sdk.stservo_def import ...`
   to the `soarm_sdk` equivalents — same symbol names, confirmed identical.
4. Update `fullstack-manip/docs/hardware-and-servo.md`, which currently documents
   `stservo-sdk` as if it's a first-party part of that repo.

Small, contained, high-value — and independent of whether the bigger migration
below ever happens.

**Landed as:** all 4 steps, on `fullstack-manip` branch `resolve-soarm-sdk-fork`.
`stservo-sdk/` deleted entirely; `hardware_interface.py`/`servo_robot.py` import
`soarm_sdk` directly (identical symbol names, confirmed via `diff`, so it was a
straight rename — also dropped the `sys.path` bootstrap hack that pointed at
`stservo-sdk/src`, no longer needed); `soarm-sdk` added as a new `hardware`
extra in `pyproject.toml` (git dependency, since it isn't on PyPI yet); and
`README.md` / `docs/{README,hardware-and-servo,roadmap}.md` updated — the
homing/calibration tool docs now point at `soarm_sdk`'s own `examples/` and
README instead of re-documenting a dashboard UI that had already diverged
(the Streamlit homing dashboard was removed from `soarm_sdk` in favor of a
Viser one with a different tab set, which this doc hadn't caught up with).
Smoke-tested by importing both edited modules against the real installed
`soarm_sdk` package — clean.

**Bonus, found while verifying this:** `docs/README.md`'s "What Is Implemented"
table had 4 stale `core/`-prefixed paths unrelated to the fork
(`manip_plant.py` and `visualization.py` actually live in `extensions/`,
`gripper.py` in `robots/`, `collision.py` in `kinematics/`) — fixed in the same
commit since they were directly adjacent and cheap to verify.

**Not fixed, flagged as a separate follow-up:** the same file's "Repository
Map" tree omits `kinematics/`, `robots/`, `extensions/`, `recording/`, and
`teleop/` entirely; its Quickstart section references example scripts that
don't exist (`examples/control/pick_place.py`, `examples/planning/pick_place_modular.py`,
an `examples/visualization/` directory, `trajectory_analysis.py`,
`controller_analysis.py`); and its "Examples suite (8 scripts)" /
"Unit tests (32 passing)" counts don't match what's actually in the repo (7
example scripts; 8 test files / ~120 test functions, unverified pass count —
`mujoco` and `scipy` weren't installed in the environment used to check this).
This is a real doc-audit task, independent of the fork resolution — not done
here to avoid unrequested scope creep on top of an already-large change.

---

## Part A+ — RobotInterface layer — ✅ Done

Added after a clarified statement of `soarm_sdk`'s actual goal: serve as an
**independent interface package** for high-level applications, against
**real hardware or a simulation equivalent** — not a giant package forcing
unrelated dependencies on every consumer. `m5teleop`'s `SimInterface` (viser)
and lerobot-backed `ArmInterface` stay exactly as they are; lerobot earns its
keep there (dataset recording, training, deployment via `soarm_learn`) and
isn't being displaced. This un-gates the narrow slice of Part B that's
specifically "the interface contract + one real-hardware implementation of
it" — not kinematics/planning/control/execution/simulation, which stay gated
below.

**Landed as** (branch `add-robot-interface`, all flat top-level modules in
`soarm_sdk`, matching its existing style — no `manip`-style subpackage):

| Module | What | Source |
|---|---|---|
| `types.py` | `Pose`, `JointState` | ported from `core/types.py` (dropped `PlanningResult`, `TeleoperatorAction` — planning/teleop-specific, still gated) |
| `interfaces.py` | `RobotInterface` Protocol | ported from `core/interfaces.py` (dropped `GripperInterface`/`MotionPlannerInterface`/`ControllerInterface`/`CollisionCheckerInterface`/`IKSolverInterface`/`TeleoperatorInterface`/`TelemetryLoggerInterface` — all relate to still-gated subsystems) |
| `rate_limiter.py` | `RateLimiter` | ported from `utils/loop_rate_limiters.py` |
| `robot.py` | `Robot` ABC, `load_robot_config()` | ported from `robots/robot.py` |
| `servo_robot.py` | `ServoRobot(Robot)` | ported from `robots/servo_robot.py` |
| `hardware_interface.py` | `ServoHardwareInterface` | ported from `core/hardware_interface.py` (already using `soarm_sdk` imports as of A4 — this pass just relocated it and switched to relative imports) |
| `configs/soarm100.yaml` | robot config | ported from `robots/configs/soarm100.yaml`, **trimmed**: dropped the `simulation:`/`gripper:`/`ee_site_name`/`ee_body_name` blocks, since nothing in this package's `Robot`/`ServoRobot` reads them and shipping unused MuJoCo-asset paths here would be misleading dead config |

**Deliberate deltas from a literal port** (enforcing simplicity over fidelity):

- Dropped the redundant `core/state.py` `RobotState` dataclass entirely.
  It was structurally identical to `JointState` (different field names only)
  and existed solely so `ServoHardwareInterface.get_robot_joint_state()`
  could return it, immediately followed by `ServoRobot.get_joint_state()`
  converting it back to `JointState` one call later. `ServoHardwareInterface`
  now returns `JointState` directly — one type, no conversion step, and
  `core/state.py`'s other classes (`StateManager`, `ObjectState`,
  `GripperState`, `TaskState` — genuinely part of the still-gated
  `ManipulationPlant` orchestration layer) didn't need to come along for it.
- Added `get_joint_state()` to the `RobotInterface` Protocol. The upstream
  Protocol didn't declare it even though the `Robot` ABC requires every
  subclass to implement it as `@abstractmethod` — a pre-existing fidelity
  gap between that repo's Protocol and its own ABC. Fixed here rather than
  reproduced.
- Dropped `ServoRobot`'s backward-compat shim methods
  (`get_robot_joint_positions`/`set_robot_joint_positions` aliases) — they
  existed only for that repo's own pre-`Robot`-ABC legacy callers, which
  don't exist in this fresh module.
- Cleaned up `hardware_interface.py`'s imports while porting: dropped two
  imports the original file had but never used (`GroupSyncWrite`, `STS_ACC`
  — the sync-write path goes through `sts.groupSyncWrite`, not a direct
  `GroupSyncWrite` reference), and removed a stray mid-file
  `from dataclasses import ...` that belonged at the top.

**Also landed in this pass:** removed `streamlit>=1.38` from `soarm_sdk`'s
base `dependencies` — confirmed via `grep` that zero files in the package
import it (the `examples/calibrate.py --ui` TUI is plain `print()`-based, no
TUI library at all; streamlit was dead weight left over from an earlier,
different dashboard). Added `numpy>=1.24` and `pyyaml>=6.0` as new base
dependencies — both genuinely needed now (`JointState`/`Pose` arrays,
`load_robot_config`'s YAML path), both lightweight relative to what was
removed.

**Tests:** 4 new files (`test_types.py`, `test_robot.py`,
`test_servo_robot.py`, `test_hardware_interface.py`), 31 tests, all against
pure logic or pre-seeded internal state — no real hardware needed. `connect()`
itself (opens a real serial port, starts a background thread) is intentionally
untested here, same rationale as A1: not worth mocking the full serial stack
for the coverage gained.

**Not touched, by explicit instruction:** `m5teleop`'s `SimInterface` and
lerobot-backed `ArmInterface`, and `soarm_learn` — none of these were retyped
against the new `RobotInterface` Protocol. They can satisfy it structurally
without any code change or new dependency on `soarm_sdk` if that's ever
useful, but doing that retyping wasn't part of this pass.

---

## Part B — fullstack_manip migration: gated, not scheduled

Do not treat this as a backlog to work through. Each subsystem migrates only when
a concrete task on real hardware needs it — otherwise it stays in `fullstack-manip`
unmigrated indefinitely. That's a fine outcome, not a failure to clean up.

### Trigger conditions

| Subsystem | Migrate when... |
|---|---|
| `kinematics/ik_solver.py`, `limits.py` | A task needs IK against a target the mink/DAQP backend actually handles better than `m5teleop`'s existing pink+pinocchio path — not just "because it's there." Two permanent IK stacks for one 6-DOF arm is duplicated logic, not optionality, unless there's a real reason to keep both. |
| `planning/motion_planner.py`, `RRTPlanner`, `min_jerk`/`topp_ra` generators | There's an actual non-teleop scripted-motion task to run on the real arm (e.g. autonomous pick-and-place) that `m5teleop`'s real-time cascade controller can't serve. |
| Any of the 7 `extensions/` controllers (impedance, admittance, force, gravity-comp, pick-place, visual-servo, OSC) | One at a time, only the specific controller a real task needs — never migrate the set because it's a matched collection in the source repo. |
| `recording/EpisodeRecorder`, `analysis/{telemetry,rerun_logger,plot_*}` | Only if `soarm_learn`'s existing recorder / whatever telemetry it has today has a specific, named gap. Check for that gap before assuming these are additive. |
| `simulation/` (MuJoCo), `execution/` (behavior trees), `ManipulationPlant` | Not until there's a multi-step task-level behavior actually running against hardware that needs sequencing beyond a single controller call. |
| `teleop/{phone,leader_follower}_teleop.py` | Only once there's a second physical input device or leader arm to actually drive them — they're stubs today. |

### If/when a piece is triggered: target shape

Keep this part of the earlier plan — it was structurally right, just applied too
early. When something is actually triggered:

- **New sibling package, `soarm_manip`** — not folded into `soarm_sdk`. One-directional
  dependency (`soarm_manip` imports `soarm_sdk`'s bus/protocol; `soarm_sdk` never
  imports `soarm_manip`). This keeps the driver's release cadence independent of
  the algorithms stack's.
- Internal layout mirrors fullstack_manip's own design, which is genuinely good and
  doesn't need to change: lean core (types + Protocol interfaces, zero heavy deps)
  + lazy/optional extensions (mink, mujoco, coal/trimesh, rerun, matplotlib all
  behind either lazy imports or `try/except ImportError`, per the existing code).
- Only stand up `soarm_manip`'s `pyproject.toml`, CI, and versioning once there's
  more than a trivial amount of code in it — don't pre-build the scaffolding for
  a package with one file in it.

### Reference: file-by-file mapping (unscheduled — consult per-subsystem when triggered)

Kept from the original draft since the mechanical analysis is still accurate and
saves re-deriving it later. **This is not a checklist to execute in one pass.**

| Source (`fullstack_manip/`) | Target (`soarm_manip/`) | Notes |
|---|---|---|
| `core/types.py`, `core/interfaces.py` (`RobotInterface` only) | `soarm_sdk/types.py`, `soarm_sdk/interfaces.py` | ✅ **Done in Part A+**, landed directly in `soarm_sdk` (flat, not `soarm_manip`) — see above. `core/collision_backends/*.py` and the rest of `core/interfaces.py`'s Protocols remain unmigrated/gated. |
| `robots/robot.py`, `robots/servo_robot.py`, `robots/configs/soarm100.yaml` | `soarm_sdk/robot.py`, `soarm_sdk/servo_robot.py`, `soarm_sdk/configs/soarm100.yaml` | ✅ **Done in Part A+.** `robots/gripper.py` (`SimGripper`/`ServoGripper`) was not ported — no gripper-specific interface exists yet, `ServoRobot` treats the gripper as an ordinary joint. |
| `kinematics/ik_solver.py`, `limits.py`, `collision.py` | `kinematics/` | Still gated — unrelated to Part A+, which didn't touch anything under `kinematics/`. `ik_solver.py` does not hard-import `mink` at module level — lazy, only needed if the mink backend is actually selected. |
| `planning/motion_planner.py`, `sampling/rrt_planner.py`, `trajectory_generators/{min_jerk,topp_ra}.py`, `task/task_planner.py` | `planning/` | `motion_planner.py` and `rrt_planner.py` hard-import `scipy.interpolate.CubicSpline` at module level — real new dependency, not lazy. |
| `control/motion_executor.py`, `high_level/*.py`, `low_level/*.py` | `control/` | — |
| `recording/recorder.py`, `replayer.py` | `recording/` | Compare against `soarm_learn.TeleopRecorder` for actual gaps before migrating. |
| `analysis/telemetry.py`, `rerun_logger.py`, `plot_*.py` | `analysis/` | `rerun_logger.py` and `plot_*.py` degrade gracefully without `rerun-sdk`/`matplotlib` installed — already lazy. |
| `utils/loop_rate_limiters.py` | `soarm_sdk/rate_limiter.py` | ✅ **Done in Part A+.** `utils/rate_config.py` (`RateConfig`) remains gated — unrelated, belongs to the `control/` layer. |
| `core/hardware_interface.py` (`ServoHardwareInterface`) | `soarm_sdk/hardware_interface.py` | ✅ **Done in Part A+** — resolved directly into `soarm_sdk`, settling the "open question" this row used to flag. Also dropped the redundant `RobotState` return type (see Part A+ above) and two unused imports (`GroupSyncWrite`, `STS_ACC`) carried over from the original. |

Deferred test ports, if/when triggered: `test_lean_core.py`, `test_planning_additions.py`,
`test_rate_config.py` map cleanly to the curated set above.
`test_collision_backends.py` hard-imports `mujoco` — gate with `pytest.importorskip`.
`test_config.py`, `test_manip_plant.py`, `test_behavior_trees.py` test subsystems
still out of scope (`ComponentFactory`/`PlantConfig`, `ManipulationPlant`, behavior
trees) — don't port until those subsystems are triggered too.

**License note, still relevant whenever this happens:** `fullstack-manip` is
Apache-2.0, `soarm_sdk`/`soarm_manip` would be MIT. Same author owns both, so not
a legal blocker — just decide consciously and be consistent.
