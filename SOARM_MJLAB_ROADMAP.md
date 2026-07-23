# soarm_mjlab Roadmap

Status (2026-07-23): **Phases 0–3 done. Phase 4 in progress** —
tooling (vast.ai remote training guide, HF Hub publish script) and the first
real training campaign (11 runs, v1–v11, on a rented vast.ai RTX 3090) are
done; the best checkpoint (v9, ~30% episode success / ~0.04 m position error)
did **not** clear the stated ≥90% promotion bar, so Phase 4 stays open until
a later campaign does. See `soarm_mjlab/docs/vast_ai_training.md` (how to
rent/run/retrieve) and `soarm_mjlab/docs/reach_training_debug_log_v1_v11.md`
(the v1–v11 tuning case study) for the artifacts this phase produced.

Written after reading `unitree_rl_mjlab` (a real mjlab application repo) end
to end; see that repo's `src/tasks/velocity/` for the pattern this roadmap
adapts.

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
      --extra cu128` correctly errors). `mujoco-warp==3.10.0.3` stays an
      explicit hard pin (documented intent, matching mjlab's own `~=3.10.0`
      tightened); `uv.lock` is committed and pins the *entire* resolved
      tree on top of that — the actual reproducibility guarantee, stronger
      than the Phase-0-original two hand-picked pins. (Pins re-bumped once
      during Phase 4: `mjlab 1.5.0→1.5.3`, `mujoco-warp 3.10.0.2→3.10.0.3`,
      which landed the upstream fix for the `num_envs>1` bug the Phase 1
      compat shim worked around — see Phase 1.)
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
│   ├── _mjlab_compat.py              # (deleted in Phase 4 — mjlab 1.5.3 fixed the bug)
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
automatically on `import soarm_mjlab.tasks`. **Resolved in Phase 4**: the
upstream fix landed in `mjlab 1.5.3` / `mujoco-warp 3.10.0.3`, so the shim
was deleted (commit `8c56a77`) and the pins bumped to match — the guard
was a no-op once the tensors were already broadcast to `nworld`, so removal
was behavior-preserving.

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
  actually lint/run.) Runs with `MUJOCO_GL=disabled` (added in Phase 4,
  commit `b5d3c7a`) so the headless Linux runner doesn't try to open a
  render context the test layers don't need.
- **`train-smoke` job** (does not block merge): a longer-but-still-small PPO
  slice (`num-envs=16`, `max-iterations=20`, ~15s locally) than the `fast`
  job's own 2-iteration smoke test, uploading the checkpoint + tensorboard
  log as a build artifact. Triggered on `push` to `main`/`master`
  (post-merge), `release` (`published`), or `workflow_dispatch` — never on
  `pull_request`, so it structurally cannot gate a merge without needing
  any branch-protection configuration. (Changed in Phase 4, commit
  `9b8ae84`, from the original nightly-`schedule` trigger to push/release:
  a nightly cron was too slow to catch a reward-curve regression — a broken
  merge would land and the signal wouldn't arrive until the next 03:00 UTC
  run — whereas post-merge push catches it within minutes. The `pull_request`
  exclusion is preserved so it still can't block the merge itself.) Runs
  on `ubuntu-latest` with `MUJOCO_GL=disabled`: no GPU-capable runner is
  configured for this repo, so the roadmap's "if one exists" doesn't apply
  yet — revisit if/when one does.

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

## Phase 4 — Real training run & promotion criteria — 🔄 In progress

This is manual/GPU work, not something to script into CI. Two halves:
**tooling** (done) and the **training campaign itself** (first campaign
done, did not clear the bar — stays open).

### Tooling — ✅ Done (commit `cd37606`, 2026-07-19)

- [x] **`docs/vast_ai_training.md`** — end-to-end guide to running a real
      training run on a rented vast.ai GPU: instance selection (RTX 3090/
      4090 tier — this task has no vision and a tiny MLP, so A100/H100 is
      wasted compute), cost (~$0.30–0.60/hr interruptible for a 4090,
      mid-2026), one-time remote setup (`scripts/setup_remote.sh` installs
      `uv`, clones the repo, `uv sync --extra cu128`), W&B auth, launching
      training inside `tmux` (SSH sessions drop — a multi-hour run must not
      die with them), live monitoring via W&B or a tensorboard SSH tunnel,
      retrieving the checkpoint (auto-uploaded to W&B, or `scp`), local
      sim playback, publishing to the HF Hub, and shutting the instance
      down (destroy, not stop — stopped instances still bill for disk).
      Written so the rented box only ever needs `soarm_mjlab` itself (the
      MJCF + meshes are vendored in-repo, no cross-submodule references at
      runtime), not the full `soarm-ws` monorepo.
- [x] **`scripts/setup_remote.sh`** — the one-time setup the guide
      references: `curl`-installs `uv`, clones `soarm_mjlab`, runs
      `uv sync --locked --extra cu128 --group dev`. Idempotent.
- [x] **`scripts/push_to_hub.py`** — publishes a promoted checkpoint to the
      Hugging Face Hub: downloads the ONNX export + configs from a W&B run
      (or a local `--run-dir`), generates a model card with training
      provenance (iteration count, `num_envs`, git commit, W&B run URL),
      pushes `policy.onnx` + `model.pt` + `env.yaml`/`agent.yaml` +
      `README.md` to a new or existing HF model repo. Deliberately a manual
      publish (only once a checkpoint clears the promotion bar), not an
      automatic upload on every checkpoint — unlike the W&B upload, which
      is automatic and happens every `save_interval`.
- [x] **Promotion bar defined *before* the run finished** (in
      `vast_ai_training.md` step 7, not after looking at the number):
      `Metrics/ee_pose/episode_success` ≥ 0.90 over the last ~100 logged
      episodes, `Episode_Termination/joint_limit_violated` ≈ 0,
      `Metrics/ee_pose/position_error` small relative to the target box.
      Stated up front so it can't quietly move to match whatever the run
      produced.

### First training campaign (v1–v11) — ✅ Done; did not clear the bar

- [x] Ran `scripts/train.py SoArm100-Reach` with real hyperparameters
      (`num_envs=4096`, `max_iterations=1500`) on a rented vast.ai RTX 3090
      — 11 runs (v1–v11), tracked via W&B (project `mjlab`, entity
      `thanhndv212-thanh-nguyen`). Full tuning history recorded in
      `docs/reach_training_debug_log_v1_v11.md` as a debugging case study
      so future campaigns start from here instead of re-discovering the
      same failure modes.
- [x] `scripts/play.py` used to visually inspect rollouts in the MuJoCo
      viewer locally on the MacBook (checkpoint pulled straight from W&B,
      no manual `scp`).

**Outcome:** the policy went from **0% success** (v1, a unit/scale bug —
action scale so small the arm physically couldn't reach the targets) to a
stable **~30% episode success / ~0.04 m position error** plateau (v9, the
best checkpoint of the session). The biggest single win was v8: fixing the
reachable-workspace mismatch — `_compute_reachable_workspace` sampled target
poses from the *full hard joint-limit range*, but the policy's action range
is capped at `home ± action_scale`, so a meaningful fraction of the target
box was physically unreachable regardless of training quality. Tightening
the FK sampling range to `[home - scale, home + scale]` doubled success and
cut position error 40%.

**This did not clear the ≥90% bar.** That's a Phase 4 finding, not a reason
to lower the bar after the fact — the ~0.03–0.04 m position-error plateau
reproduced identically at 56× the data (v11: `num_envs=230,000`, 7.6 B total
env steps, ~2 h 35 m on the 3090), confirming it's a robust limit of the
current reward/action setup, not a "just needs more samples" problem. The
debug log's "Open leads" section lists four untested hypotheses for pushing
past it (joint-vel observation noise, two-scale reward shaping, LR/action-
scale annealing, performance-gated curriculum) — none tried yet.

| | v1 (broken baseline) | v9 (best) |
|---|---|---|
| `episode_success` | 0% | ~30% (avg), 75% (peak) |
| `position_error` | 0.34 m | 0.03–0.04 m |
| `orientation_error` | 2.12 rad | 0.7 rad (untracked by success — harmless) |
| `mean_reward` | -8.33 | +59 (not directly comparable — reward terms changed) |

Best checkpoint: v9, W&B run
[`thanhndv212-thanh-nguyen/mjlab/y4bomfz3`](https://wandb.ai/thanhndv212-thanh-nguyen/mjlab/runs/y4bomfz3),
`model_1499.pt`.

### Remaining (still open)

- [ ] A later campaign that clears the ≥90% promotion bar — starting from
      the v9 config and the debug log's open leads, not from scratch.
- [ ] Only then: `scripts/push_to_hub.py` to publish the promoted checkpoint
      to the HF Hub (the script exists and is tested, but has not been run
      against a real promoted checkpoint yet — no checkpoint has cleared
      the bar to promote).

## Phase 5 — Sim2real deployment via RobotInterface

Gated on Phase 4's remaining work: no checkpoint has cleared the ≥90%
promotion bar yet, so there is nothing to deploy. The v9 checkpoint (~30%
success) is good enough to *develop* the deploy script against (it moves
the arm meaningfully), but not good enough to *validate* sim2real on —
doing so would test the deployment plumbing, not a policy worth deploying.

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
