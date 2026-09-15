---
name: soarm-tamp
description: 'Work in soarm_tamp — long-horizon TAMP (long_tamp on HPP) planning motion for the physical SO-101, with planning in a Docker container and execution on the host. Use for planning a pick-and-place or a TCP-pose reach, the hpp_container.sh workflow, the plan-and-run dashboard, run manifests, replaying in the viser viewer, streaming a trajectory to the arm, validating joint calibration, scene/asset regeneration, or when the arm lags, stalls, clamps, or will not follow a planned path.'
---

# soarm_tamp — Long-Horizon TAMP → Physical SO-101

Path: `soarm_tamp/` · v0.1.0 · hatchling, flat layout · **Python ≥3.11** ·
no hard dependencies · extra `[host] = ["soarm_sdk"]`

First task: pick a 25 mm cube from A and place it at B. **Everything here has been run
on the physical arm** — TCP within 7.0 mm / 2.2° of the commanded pose.

## The two-process split — the thing to understand first

Planning and execution **never share an interpreter**. `pyhpp`/`long_tamp` exist only
inside the HPP container; the servos exist only on the host. The contract is a file:

```
plan (container, pyhpp) → runs/<name>/manifest.json → execute (host, soarm_sdk)
```

`pyproject.toml` deliberately declares **no** dependencies for this reason — declaring
either half would make the package uninstallable in the other place. Each is imported
at point of use. Do not "fix" this by adding `long_tamp` to dependencies.

Live mirroring uses the same trick: `execute.py` appends every issued command to
`<run>/live.jsonl`, and `replay.py --follow` tails it. A file is the whole channel.

## Running it — CLI

```bash
# simplest thing the stack can plan: move the TCP to a pose
./scripts/hpp_container.sh tcp --out runs/tcp01 --xyz 0.22 0.0 0.05 --rpy 180 0 0

# plan the pick-and-place (creates/starts the container as needed)
./scripts/hpp_container.sh plan --out runs/cube01 --viewer none

# watch it — viser on http://localhost:8000
./scripts/hpp_container.sh replay --run runs/cube01

# what would be sent, no hardware
python -m soarm_tamp.execute runs/cube01 --dry-run

# run it
python -m soarm_tamp.execute runs/cube01 --port /dev/cu.usbmodemXXXX

# live mirror: start the follower FIRST, then execute
./scripts/hpp_container.sh replay --run runs/cube01 --follow
python -m soarm_tamp.build_assets            # after editing geometry.py
```

`hpp_container.sh` subcommands: `up`, `plan`, `tcp`, `replay`, `shell`, `exec`.
Container `hpp-soarm-tamp`, image `hpp-agimus:arm64`, bind-mounting `$HOME/devel/hpp`,
`$LONG_TAMP_DIR` (default `~/Develop/agimus-ws/long-tamp`) and this workspace. It
deliberately uses its **own** container name — the pre-existing `hpp-agimus-arm64`
container has no mount for `soarm-ws`, and recreating it would discard its writable
layer. Nothing here touches it.

**Viser runs on port 8000**, not the 8080 that `long_tamp`'s own "Viser viewer started"
log line prints — that message falls back to a stale constant. Trust `replay.py`.

## Running it — dashboard

`python -m soarm_tamp.dashboard [--device --baud --port --urdf --no-stream]` launches a
Viser dashboard (default port 8080) that wraps the same host-side pieces behind three
tabs, built on `soarm_sdk.dashboard`. **Tab order is the order to press them in**: bring
the arm up (Start Up, from `soarm_sdk`'s setup panel) and confirm the mirror tracks,
prove the pipeline with a single TCP goal, then run the pick-and-place — each step only
makes sense once the one before it works.

- **TCP Plan** — plan and preview a single Cartesian goal, then execute against the real
  arm.
- **Pick & Place** — the full pick-and-place, previewed via a ghost mesh before
  streaming.
- **Execution Watchdog** — read-only. Flags large calibration/model deviation or
  real-arm/planning-bound divergence; **never changes offsets, signs, or servo
  limits** — that belongs to `calibrate`'s `soarm-dashboard-calibration`, not here.

The URDF default is `SO-ARM100/Simulation/SO101/so101_new_calib.urdf`, mapped through
`~/.soarm_sdk/calibration.json` so the 3-D view tracks the real arm, not a nominal zero.

## Before the first run on any arm — non-negotiable

Calibrate through `soarm-dashboard-calibration` first — **see the `calibrate` skill for
the full procedure** (reference-pose zeroing, ROM measurement, explicit acceptance
tolerances). Do not rely on `soarm-seed-calibration`'s offline travel-only seed as the
final calibration: it cannot recover direction signs and has measured wrong on this
arm's geometry. Once a calibration passes acceptance:

```bash
python -m soarm_tamp.validate_calibration --port /dev/cu.usbmodemXXXX
```

The planning URDF, `soarm_sdk` and lerobot each use a different joint-angle zero. The
mapping lives in `soarm_sdk.calibration` (shared with RL deployment, not reimplemented
here). An unvalidated calibration is written `validated: false` and **`execute.py`
refuses to stream against it**. Do not work around that refusal.
`validate_calibration.py` settles signs limp (torque off), re-confirms under power,
then requires a tape-measure FK check.

Plan from where the arm actually *is*, not from the URDF zero:

```bash
python -m soarm_tamp.read_pose --port ... --out runs/start.json         # host
./scripts/hpp_container.sh tcp --start runs/start.json --xyz ... --out runs/tcp06
```

Without `--start`, the servos slew to the plan's first waypoint along a path nothing
checked.

## Streaming — why the arm does not follow a valid plan

The first live run put the hand on the table along a path every waypoint of which HPP
had certified collision-free. The plan was fine; the assumption that streaming
waypoints makes the arm follow them was not. Four knobs, three distinct jobs:

| knob | job | default |
|---|---|---|
| `--max-step` | how finely the path is sampled (fidelity) | 0.02 |
| `--servo-clamp` | how far the command may *lead* the measurement | 0.10 |
| `--sync-tol` | how far the arm may trail the stream | 0.08 |
| `--speed-scale` | GOAL_SPEED as a multiple of the plan's own velocity | 1.5 |

**Keep `--sync-tol` above `--max-step`.** The arm then always chases a target slightly
ahead of it: the lead keeps the servos above their stiction threshold, the clamp bounds
divergence from the checked path, and the motion flows instead of stopping at every
waypoint (0 of 57 stops vs 7 of 7). `--sync` (default on) holds each waypoint until
every joint is within tolerance, so lag is bounded and a run that cannot keep up says
so (`worst lag`, `timed out waiting`) instead of announcing itself by contact.

Two counterintuitive facts, both measured: **small steps do not move servos** (0.02 rad
apart → 70% of each step, 28 clamps; 0.10 rad apart → 92%, 5 clamps), and **settle at
speed, not slowly** (creeping at 0.15 rad/s left `shoulder_lift` 0.052 rad short every
time; the same error at default speed closes). `--settle-tol` defaults to 0.05 because
gravity droop against finite position-control stiffness leaves the loaded joint
0.03–0.05 rad short — re-commanding cannot close it, the servo believes it has arrived.

Other flags: `--dry-run`, `--dry-run --pace` (streams nothing but takes as long as the
real run, to drive the mirror at true speed), `--no-plan-timing` (flatten a
time-parameterized segment to a constant rate), `--no-trace`.

**Diagnosing one joint:** `python -m soarm_tamp.joint_test --port ... --joint elbow_flex
--delta 0.3 --single --hand-is-clear`. `--single` is the mapping check — measured
excursion over commanded, near 1.0 is correct. The laddered mode measures step
completion instead and **must not be read as a mapping check**.

## Scene, reach, and known model gaps

- Arm bolted to the `z = 0` plane. Cube A = (0.22, −0.10) → B = (0.22, +0.10), metres,
  base frame, inside the verified top-down annulus (r = 0.10–0.30 m).
- **25 mm cube**, not arbitrary: `studies/reachability.py` measured jaw opening vs the
  `gripper` angle — 29 mm clearance at +10°, 19.8 mm at 0°.
- **5-DOF mask** `<mask>1 1 1 1 1 0</mask>` on the cube's handle. Five arm joints
  against six grasp equations is solvable only where the system is degenerate; freeing
  rotation about the approach axis costs no reachability (~170° usable yaw across a
  600k-sample sweep).
- Ceiling for a top-down reach at x = 0.22 is **z ≈ 0.08 m** — IK finds nothing at
  0.10 m, and tilting 30° off vertical finds nothing at any height at that radius. On a
  5-DOF arm orientation is coupled to position; "move it higher for safety" runs out.
- **The table is a thin slab, so the half-space beneath it reads as free space.** HPP
  will call a hand-below-the-table pose collision-free; it only catches paths that
  cross the slab. With fingertips ~8 mm past the TCP frame and the collision box
  recessed 3 mm, a hand resting on the real table can be "valid" in the model.
- TCP-pose coverage is **17 of 20** top-down targets; the three failures are at
  r ≈ 0.11–0.12 m, failing inside `TransitionPlanner.computePath` on a self-collision
  (`shoulder_link` vs `gripper_link`/`moving_jaw`) on all 10 retries. Open question.

## Layout

`plan.py` (pick-and-place), `plan_tcp.py` (single Cartesian goal via
`GraspSequencePlanner.plan_loop()`), `replay.py`, `execute.py`,
`validate_calibration.py`, `read_pose.py`, `joint_test.py`, `build_assets.py`,
`geometry.py`, `conventions.py`, `studies/reachability.py`, `dashboard/` (the
plan-and-run Viser dashboard: `app.py`, `panels/tcp.py`, `panels/pickplace.py`,
`panels/watchdog.py`, `container.py`, `player.py`), `config/cube_pick_place.yaml`,
`generated/` (so101, cube, table URDF+SRDF), `runs/`.

**No test suite, no CI.** The README (354 lines) is the real reference and is unusually
detailed on hardware behaviour — read `Streaming a trajectory the arm can actually
follow` before any first run on a new arm. Related: `long-tamp` in the sibling
`agimus-ws` workspace is the planning library this drives.
