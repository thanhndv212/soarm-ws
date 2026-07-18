# soarm_mjlab Roadmap

Status (2026-07-18): **Phases 0–3 done.** Written after reading
`unitree_rl_mjlab` (a real mjlab application repo) end to end; see that
repo's `src/tasks/velocity/` for the pattern this roadmap adapts.

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

## Phase 0 — Repo scaffolding & DevOps baseline — ✅ Done

Mirrors how `soarm_sdk`/`soarm_lerobot` were set up, except for install
tooling (below) — no other new conventions invented.

- [x] New GitHub repo `thanhndv212/soarm_mjlab` (public), added to `soarm-ws`
      as a git submodule.
- [x] `pyproject.toml`: setuptools + flat layout (matches `soarm_lerobot`'s
      convention, not `soarm_sdk`'s hatchling/`src` one — this package is
      closer in kind to the training-side packages).
- [x] **Install tooling: `uv`, not pip** — the one package in `soarm-ws`
      that installs this way. Reason: `mjlab` itself gates `torch` behind
      mutually-exclusive `cpu`/`cu128` extras routed to different package
      indices (CPU vs CUDA wheels via `[tool.uv.sources]`), which pip has
      no equivalent for short of hand-juggling `--extra-index-url`. Our
      own `pyproject.toml` forwards the same two extra names to
      `mjlab[cpu]`/`mjlab[cu128]`, mirrors mjlab's source-routing (gated on
      our own extras — `[tool.uv.sources]` doesn't propagate from a
      dependency's own pyproject.toml), and declares `[tool.uv.conflicts]`
      so both can't be selected together (verified: `uv sync --extra cpu
      --extra cu128` correctly errors). `mujoco-warp==3.10.0.2` stays an
      explicit hard pin (documented intent, matching mjlab's own `~=3.10.0`
      tightened); `uv.lock` is committed and pins the *entire* resolved
      tree on top of that — the actual reproducibility guarantee, stronger
      than the Phase-0-original two hand-picked pins.
- [x] `Makefile` (`sync`, `sync-cpu`, `lint`, `test`, `test-cpu`, `check`),
      copied down from mjlab's own to the subset we actually need (no
      docs/build/publish targets — not a published library).
- [x] `ruff` — no repo-level override, same as `soarm_lerobot`, so defaults
      (88-char) match `soarm_sdk`'s too.
- [x] `LICENSE` (MIT), `CHANGELOG.md`, `py.typed`.
- [x] `.github/workflows/ci.yml` — `astral-sh/setup-uv` + `uv sync --locked
      --extra cpu --group dev` (fails the build on lockfile drift) + lint +
      `pytest`. One `fast` job for now; the `train-smoke` second job is
      added in Phase 1 once `scripts/train.py` and the Reach task exist to
      smoke-test.

**Exit criteria:** ✅ `uv sync --extra cpu --group dev` (`make sync-cpu`)
succeeds in a clean environment; `uv run ruff check soarm_mjlab tests` and
`uv run pytest` both pass on the empty-but-structured package (1 sanity
test: package imports). Verified locally on macOS arm64 — the Linux
CUDA/CPU index-routing half of `[tool.uv.sources]` is exercised for the
first time by CI itself (`ubuntu-latest`), not verified on the dev machine.

## Phase 1 — Sample task MVP: "Reach" — ✅ Done

Directory layout (mirrors `unitree_rl_mjlab`'s `src/tasks/velocity/` shape,
scaled down to one task; flat `soarm_mjlab/` package, not `src/` — matches
Phase 0's actual setuptools layout, not the `src/` sketch originally drafted
here):

```
soarm_mjlab/
├── pyproject.toml
├── CHANGELOG.md
├── .github/workflows/ci.yml
├── soarm_mjlab/
│   ├── __init__.py
│   ├── _mjlab_compat.py              # works around an mjlab==1.5.0 num_envs>1 bug
│   ├── assets/robots/so_arm100/
│   │   ├── __init__.py
│   │   ├── so_arm100_constants.py    # actuator cfg (STS3215 gains, from the MJCF's
│   │   │                             #   own sts3215 default class — soarm_sdk's
│   │   │                             #   configs/soarm100.yaml has no PID gains to
│   │   │                             #   seed from, contra the original plan below),
│   │   │                             #   home keyframe, collision cfg.
│   │   └── xmls/                     # MJCF + meshes vendored from SO-ARM100/Simulation/SO101
│   ├── tasks/reach/
│   │   ├── __init__.py
│   │   ├── reach_env_cfg.py          # make_reach_env_cfg() factory
│   │   ├── mdp/
│   │   │   ├── observations.py       # ee_pose_error
│   │   │   ├── rewards.py            # distance_to_target
│   │   │   ├── terminations.py       # task_success, joint_limit_violated
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
├── deploy/                           # reach_policy_runner.py — Phase 5, not yet
└── tests/                            # see Phase 2
```

Task definition: target end-effector pose sampled uniformly within a
reachable-workspace box (derived from joint limits + FK via a throwaway
compiled model in `config/so_arm100/env_cfgs.py`, not hand-picked); episode
ends on `task_success` (distance below threshold for N consecutive steps),
`time_out`, `joint_limit_violated`, or `ee_ground_collision`. Reward =
negative position error (`distance_to_target`) + `action_rate_l2` +
`joint_pos_limits` penalty — deliberately the smallest reward set that
produces a non-degenerate policy; orientation error is sampled and observed
but not yet scored (`orientation_weight=0.0` — a 0-weighted target gives the
policy no incentive to satisfy it, so raise it deliberately before relying
on it, not as a silent default).

**Exit criteria:** ✅ `python scripts/train.py SoArm100-Reach
--env.scene.num-envs=4 --agent.max-iterations=2 --gpu-ids None` runs to
completion with no exceptions and a non-NaN reward curve (`--gpu-ids None`
needed on this dev machine — no CUDA device, and the default assumes GPU 0
exists). Verified on macOS arm64 (CPU only). This is not "the policy
works" — it's "the pipeline doesn't crash," which is the correct Phase 1
bar; policy quality is Phase 4.

Found and fixed one real bug along the way, not specific to Reach: mjlab
1.5.0 crashes on reset with `num_envs > 1` for any entity whose joint
limits are never touched by a domain-randomization event (reproduces on
mjlab's own bundled `Mjlab-Lift-Cube-Yam` task, not just SO-ARM100) —
`mujoco_warp` keeps such fields at a broadcastable `(1, ...)` shape until
DR'd, and `Entity.initialize` doesn't broadcast to `nworld` before slicing
per-env. Worked around in `soarm_mjlab/_mjlab_compat.py`, applied
automatically on `import soarm_mjlab.tasks`; safe to delete once mjlab
ships a fix.

## Phase 2 — Testing & validation strategy — ✅ Done (layers 1–4)

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

**Exit criteria:** ✅ `tests/test_mdp_reach.py`, `test_asset_so_arm100.py`,
`test_env_reach.py`, `test_train_smoke.py` all exist and pass (24 tests,
~17s locally); CI is red if any of layers 1–4 breaks — no workflow changes
needed, the existing `fast` job (`FORCE_CPU=1 uv run pytest`) already picks
all four up. `tests/conftest.py` adds a `FORCE_CPU`-aware `get_test_device()`
helper, matching mjlab's own test convention.

Layer 4 (`test_train_smoke.py`) runs `scripts/train.py` as a real subprocess
(not an in-process call) in a `tmp_path` cwd, so it also exercises tyro CLI
parsing and confirms a checkpoint + ONNX export land on disk —
`--agent.logger tensorboard` avoids a real W&B run per test invocation
(training with the default `wandb` logger, as done manually while verifying
Phase 1, actually pushes a run to the configured W&B account).

## Phase 3 — CI/CD — ✅ Done

Two jobs, deliberately not one, because they have different failure
semantics:

- **`fast` job** (blocks merge): `ruff check soarm_mjlab tests`, then test
  layers 1–4 above, on a standard CPU GitHub-hosted runner. Triggered on
  `push`/`pull_request` only — every PR, every push. If this is red, the PR
  does not merge — same bar as `soarm_sdk`'s existing CI. (Already existed
  from Phase 0; Phases 1–2 are what gave it Reach code and tests to
  actually lint/run.)
- **`train-smoke` job** (does not block merge): a longer-but-still-small PPO
  slice (`num-envs=16`, `max-iterations=20`, ~15s locally) than the `fast`
  job's own 2-iteration smoke test, uploading the checkpoint + tensorboard
  log as a build artifact. Triggered on `schedule` (nightly, 03:00 UTC) or
  `workflow_dispatch` only — structurally cannot run on a PR, so it cannot
  gate a merge, without needing any branch-protection configuration. Runs
  on `ubuntu-latest`: no GPU-capable runner is configured for this repo,
  so the roadmap's "if one exists" doesn't apply yet — revisit if/when one
  does.

Also: every training run dumps its fully-resolved `env.yaml`/`agent.yaml`
(via `dump_yaml`, copying `unitree_rl_mjlab`'s pattern) plus a
`git/soarm_mjlab.diff` file with the commit hash, `git status`, and full
diff (via `runner.add_git_repo_to_log(__file__)`, an existing `rsl_rl`
runner feature) into the log directory — already wired up in
`scripts/train.py` since Phase 1, not new work here. So any checkpoint,
including the ones `train-smoke` uploads, is traceable back to the exact
config and code that produced it. This matters specifically because config
drift between "what trained the policy" and "what's running now" is the
most common source of a policy that worked in one run and silently doesn't
in the next.

**Exit criteria:** ✅ a PR that breaks a reward function's return shape
fails CI within the `fast` job (verified via the layer-1/2/3 tests added in
Phase 2), in under ~2 minutes, without needing a GPU.

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
