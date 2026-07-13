# soarm_mjlab Roadmap

Status (2026-07-14): **Phase 0 done**, local-only (new repo at
`soarm-ws/soarm_mjlab/`, not yet pushed to a GitHub remote or wired in as a
submodule — see the note at the end of Phase 0 below). Written after
reading `unitree_rl_mjlab` (a real mjlab application repo) end to end; see
that repo's `src/tasks/velocity/` for the pattern this roadmap adapts.

Serendipitous finding while verifying Phase 0: `mjlab` itself ships a
built-in `mjlab.tasks.manipulation` task (`Mjlab-Lift-Cube-Yam`) — an actual
arm-manipulation example, not just legged locomotion. Worth reading its
`mdp/` alongside `unitree_rl_mjlab`'s when Phase 1 starts; it's a closer
analogue to Reach than anything in the velocity-tracking task.

## Goal

A new, independent package/submodule for RL training of SO-ARM100 in MuJoCo
(via `mjlab`), producing policies that deploy through `soarm_sdk.RobotInterface`
— the same interface real-hardware control already uses. One sample task
("Reach") carried end-to-end through train → validate → sim-deploy → real
hardware, with the scaffolding (CI, tests, config layering) built to hold a
second and third task later without rework.

## Deliberate deviations from unitree_rl_mjlab

`unitree_rl_mjlab`'s manager-based config split (task cfg / `mdp/` functions /
per-robot asset module / task registry) is worth copying as-is — it's a clean
separation and this roadmap follows it closely. Two things are **not** copied:

1. **No C++ deployment stack.** Unitree's C++ FSM + onnxruntime + a hand-mirrored
   `isaaclab/` namespace exists because a legged robot's balance controller
   needs a hard real-time loop — milliseconds of jitter and it falls over. A
   6-DOF arm driven over serial at ~50 Hz already runs its control loop in
   Python (`m5teleop/teleop.py`). The trained policy loads (ONNX or torch)
   directly inside a Python process that drives `soarm_sdk.RobotInterface` —
   one deploy script, one language, no train/deploy consistency problem to
   solve because there's only one implementation.
2. **No terrain/locomotion machinery.** Terrain generators, height-scan
   sensors, gait/contact rewards, push-perturbation events are all
   locomotion-specific and get dropped from the base config, not carried over
   as unused scaffolding.

## Phase 0 — Repo scaffolding & DevOps baseline — ✅ Done (local)

Mirrors how `soarm_sdk`/`soarm_lerobot` were set up — no new conventions invented.

- [x] New local git repo at `soarm-ws/soarm_mjlab/`, default branch `main`.
      **Not yet** pushed to a GitHub remote or added as a `soarm-ws`
      submodule pointer — that's an external/shared-state action, held for
      explicit go-ahead rather than done as a side effect of "start".
- [x] `pyproject.toml`: setuptools + flat layout (matches `soarm_lerobot`'s
      convention, not `soarm_sdk`'s hatchling/`src` one — this package is
      closer in kind to the training-side packages). **Hard-pinned**
      `mjlab==1.5.0` / `mujoco-warp==3.10.0.2` — verified installing
      together cleanly on macOS arm64 (full dep tree: torch 2.13.0,
      mujoco 3.10.0, warp-lang 1.15.0, rsl-rl-lib, tyro, viser, wandb).
      Unitree's reference repo pinned older versions (1.2.0/3.5.0); these
      are current-latest-verified, not a copy of theirs.
- [x] `ruff` — no repo-level override, same as `soarm_lerobot`, so defaults
      (88-char) match `soarm_sdk`'s too.
- [x] `LICENSE` (MIT), `CHANGELOG.md`, `py.typed`.
- [x] `.github/workflows/ci.yml` — one `fast` job for now (lint + pytest);
      the `train-smoke` second job is added in Phase 1 once `scripts/train.py`
      and the Reach task exist to smoke-test.

**Exit criteria:** ✅ `pip install -e ".[dev]"` succeeds in a clean venv;
`ruff check soarm_mjlab tests` and `pytest` both pass on the
empty-but-structured package (1 sanity test: package imports).

## Phase 1 — Sample task MVP: "Reach"

Directory layout (mirrors `unitree_rl_mjlab`'s `src/tasks/velocity/` shape,
scaled down to one task):

```
soarm_mjlab/
├── pyproject.toml
├── CHANGELOG.md
├── .github/workflows/ci.yml
├── src/soarm_mjlab/
│   ├── __init__.py
│   ├── assets/robots/so_arm100/
│   │   ├── __init__.py
│   │   └── so_arm100_constants.py   # MJCF from SO-ARM100 submodule, actuator cfg
│   │                                 #   (stiffness/damping seeded from soarm_sdk's
│   │                                 #   configs/soarm100.yaml so sim gains and real
│   │                                 #   PID gains start from the same source), home
│   │                                 #   keyframe, collision cfg.
│   ├── tasks/reach/
│   │   ├── __init__.py
│   │   ├── reach_env_cfg.py          # make_reach_env_cfg() factory
│   │   ├── mdp/
│   │   │   ├── observations.py       # joint_pos_rel, joint_vel_rel, ee_pose_error,
│   │   │   │                         #   target_pose
│   │   │   ├── rewards.py            # distance_to_target, action_rate_l2,
│   │   │   │                         #   joint_pos_limits
│   │   │   ├── terminations.py       # time_out, task_success, joint_limit_violated
│   │   │   └── commands.py           # UniformPoseCommand — random reachable target
│   │   ├── rl/runner.py
│   │   └── config/so_arm100/
│   │       ├── __init__.py           # register_mjlab_task("SoArm100-Reach")
│   │       ├── env_cfgs.py           # per-robot placeholder fill-in + play=True override
│   │       └── rl_cfg.py             # PPO hyperparams (RSL-RL)
├── scripts/
│   ├── train.py                      # thin: mirrors unitree_rl_mjlab's train.py
│   ├── play.py
│   └── list_envs.py
├── deploy/
│   └── reach_policy_runner.py        # loads checkpoint, drives soarm_sdk.RobotInterface
└── tests/                            # see Phase 2
```

Task definition: target end-effector pose sampled uniformly within a
reachable-workspace box (derived from joint limits + FK, not hand-picked);
episode ends on `task_success` (distance below threshold for N consecutive
steps), `time_out`, or `joint_limit_violated`. Reward = negative pose error +
`action_rate_l2` + `joint_pos_limits` penalty — deliberately the smallest
reward set that produces a non-degenerate policy, more terms added only if
the trained policy shows a specific failure mode (jerky motion, limit
slamming) that a specific term fixes.

**Exit criteria:** `python scripts/train.py SoArm100-Reach --env.scene.num-envs=4
--agent.max-iterations=2` runs to completion with no exceptions and a
non-NaN reward curve. This is not "the policy works" — it's "the pipeline
doesn't crash," which is the correct Phase 1 bar; policy quality is Phase 4.

## Phase 2 — Testing & validation strategy

A standard test pyramid, shaped by one constraint: real physics simulation
and GPU training cannot run in CI. Each layer is scoped so everything except
the top one *can*.

| Layer | What it covers | Runs where | Speed |
|---|---|---|---|
| 1. Unit tests | Individual `mdp/*.py` functions (reward/observation/termination math) called directly with synthetic tensors — no MuJoCo, no env | CI, every push | ms |
| 2. Config/asset validation | MJCF compiles; actuator `target_names_expr` regexes actually match joint names in the compiled model; action/observation space dims equal expected DOF (6 for SO-ARM100); every `# Set per-robot` placeholder in the base cfg is filled by the time `config/so_arm100/env_cfgs.py` returns | CI, every push | seconds |
| 3. Environment smoke test | Instantiate `ManagerBasedRlEnv` with `num_envs=2`, run `reset()` + a few `step()`s with random actions, assert: no NaN/Inf in obs/reward, reward is finite, `done` shape matches `num_envs` | CI, every push | seconds |
| 4. Training smoke test | `train.py SoArm100-Reach --agent.max-iterations=2 --env.scene.num-envs=4` on CPU — exercises the full RSL-RL wrapper → PPO update path, catches wiring bugs (shape mismatches between obs groups and network config, missing registry entries) that layers 1–3 can't see | CI, every push | ~1 min |
| 5. Full training run | Real hyperparameters, thousands of iterations, GPU, tracked via tensorboard | Manual / scheduled GPU runner — **not CI** | hours |
| 6. Sim-replay validation | Load the Phase-5 checkpoint and roll it out through the *deployment* code path (`deploy/reach_policy_runner.py` driving a `SimRobotInterface`), not the training env wrapper — confirms the deploy-time obs/action processing matches what the policy was trained on, before touching real hardware | Manual, on a dev machine | minutes |
| 7. Real-hardware validation | Staged: (a) torque-limited dry run, arm homed, operator on E-stop; (b) full-torque supervised run; (c) unattended repeated-trial soak test with logged episode outcomes (success rate, joint temps) | Manual, physical hardware | — |

Promotion gate between layers 5 and 6: a checkpoint is not touched by real
hardware until it clears a stated numeric bar on held-out random seeds (e.g.
≥90% `task_success` over 100 eval episodes) — decided when Phase 4 is
reached, not guessed now.

**Exit criteria:** `tests/test_mdp_reach.py`, `test_asset_so_arm100.py`,
`test_env_reach.py`, `test_train_smoke.py` all exist and pass; CI is red if
any of layers 1–4 breaks.

## Phase 3 — CI/CD

Two jobs, deliberately not one, because they have different failure
semantics:

- **`fast` job** (blocks merge): `ruff check src tests`, then test layers
  1–4 above, on a standard CPU GitHub-hosted runner. Every PR, every push.
  If this is red, the PR does not merge — same bar as `soarm_sdk`'s existing
  CI.
- **`train-smoke` / `nightly-eval` job** (does not block merge): optionally
  runs a slightly longer training slice (more iterations, still small) on a
  schedule or manual dispatch, on a GPU-capable runner if one exists;
  uploads the checkpoint + tensorboard log as a build artifact. Failing
  this flags a regression worth investigating, but a PR isn't blocked
  waiting on an hours-long run.

Also: every training run (Phase 4/5, not CI) dumps its fully-resolved
`env.yaml`/`agent.yaml` plus the git commit hash into the log directory —
copying `unitree_rl_mjlab`'s `dump_yaml(log_dir / "params" / ...)` pattern —
so any checkpoint is traceable back to the exact config and code that
produced it. This matters specifically because config drift between "what
trained the policy" and "what's running now" is the most common source of a
policy that worked in one run and silently doesn't in the next.

**Exit criteria:** a PR that breaks a reward function's return shape fails
CI within the `fast` job, in under ~2 minutes, without needing a GPU.

## Phase 4 — Real training run & promotion criteria

This is manual/GPU work, not something to script into CI:

- [ ] Run `scripts/train.py SoArm100-Reach` with real hyperparameters
      (`num_envs` in the thousands, full `max_iterations`) on a GPU machine.
- [ ] Track reward curve + task-specific metrics (success rate, mean
      time-to-target) via tensorboard.
- [ ] Define the promotion bar *before* the run finishes, not after looking
      at the number (avoids moving the goalposts to match whatever the run
      produced) — e.g. ≥90% success over 100 held-out-seed eval episodes,
      average joint-limit violations near zero.
- [ ] `scripts/play.py` to visually inspect rollouts in the MuJoCo viewer
      before touching layer 6/7.

## Phase 5 — Sim2real deployment via RobotInterface

- [ ] `deploy/reach_policy_runner.py`: loads the promoted checkpoint (ONNX
      export or raw torch), implements a `SimRobotInterface`-shaped
      real-hardware counterpart that calls into `soarm_sdk.ServoRobot`
      directly — same `RobotInterface` Protocol either way, so this script
      doesn't know or care whether it's driving sim or real hardware.
- [ ] Layer 6 (sim-replay validation) and layer 7 (staged real-hardware
      validation) from the Phase 2 table.
- [ ] Only after a successful staged real run: document the deployment
      procedure (this is where a short doc, not a roadmap, is the right
      artifact — see `documentation-and-adrs` territory, not this file).

## Phase 6 — Scale beyond Reach (gated, not scheduled)

Deliberately unscheduled, same philosophy as this workspace's
`MIGRATION_PLAN.md` Part B: don't build a second task's config/reward set
speculatively. Once Reach has cleared Phase 5 on real hardware, the same
`tasks/<name>/` shape (env cfg + `mdp/` + per-robot config + registry entry)
repeats for pick-place or any other task — but only when there's a concrete
task to point it at, not before.
