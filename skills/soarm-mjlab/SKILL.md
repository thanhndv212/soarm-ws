---
name: soarm-mjlab
description: 'Work in soarm_mjlab — RL training of the SO-ARM100 in MuJoCo via mjlab (PPO/rsl_rl), deployed through soarm_sdk.RobotInterface. Use for training or playing the SoArm100-Reach policy, adding MDP terms/rewards/observations or a new task, env and PPO config, uv sync and the CPU/CUDA extras, GPU/vast.ai runs, checkpoints and push_to_hub, or the vendored SO101 MJCF assets. This is the one package that uses uv, not pip.'
---

# soarm_mjlab — RL Training in MuJoCo

Path: `soarm_mjlab/` · v0.1.0 · setuptools + **uv** · Python ≥3.10

Trains policies in MuJoCo via [mjlab](https://github.com/mujocolab/mjlab) and deploys
them through `soarm_sdk.RobotInterface` — the same interface teleop and TAMP use, so a
trained policy does not distinguish sim from the physical arm.

## Install — uv, never pip

```bash
make sync-cpu     # dev machine, no GPU   (= uv sync --extra cpu  --group dev)
make sync         # GPU box, CUDA 12.8    (= uv sync --extra cu128 --group dev)
```

`mjlab` gates `torch` behind mutually-exclusive `cpu` / `cu128` extras routed to
different package indices; `pip install -e .` cannot route them. The extras are
declared conflicting in `[tool.uv.conflicts]`. **`uv.lock` is committed and CI runs
`uv sync --locked` — a stale lockfile fails the build**, so re-lock in the same commit
as any dependency change.

`mjlab==1.5.3` and `mujoco-warp==3.10.0.3` are **hard-pinned on purpose**: both are
fast-moving research libraries and an unpinned upgrade silently changes physics/API,
breaking reproducibility of existing checkpoints. Re-pin deliberately; never
`pip install -U` your way past it. (`huggingface_hub` is left unpinned — it is an
upload utility, not physics.)

## Commands

```bash
make lint        # uv run ruff check soarm_mjlab tests
make test        # uv run pytest
make test-cpu    # FORCE_CPU=1 uv run pytest
make check       # lint + test-cpu   ← run this before pushing
make format      # ruff format + ruff check --fix

uv run python scripts/list_envs.py
uv run python scripts/train.py SoArm100-Reach
uv run python scripts/play.py ...            # see README
uv run python scripts/push_to_hub.py ...     # publish a promoted checkpoint
```

**CPU smoke run** (this machine has no GPU, so `--gpu-ids None` is required — the
default assumes GPU 0 exists):

```bash
python scripts/train.py SoArm100-Reach --env.scene.num-envs=4 \
    --agent.max-iterations=2 --gpu-ids None
```

`scripts/` mirrors `unitree_rl_mjlab`'s scripts of the same name, minus
motion-tracking (no task here uses it). `scripts/setup_remote.sh` provisions a rented
GPU box.

## Package map

```
soarm_mjlab/tasks/reach/
    mdp/        observation / reward / termination terms
    rl/         ReachOnPolicyRunner
    config/so_arm100/
        __init__.py   register_mjlab_task(task_id="SoArm100-Reach", ...)
        env_cfgs.py   so_arm100_reach_env_cfg(play=False)
        rl_cfg.py     so_arm100_reach_ppo_runner_cfg()
soarm_mjlab/assets/robots/so_arm100/xmls/   vendored SO101 MJCF + meshes
```

**Task registration is an import side effect** (`register_mjlab_task`), same convention
as mjlab's own — a new task must be imported through the `tasks/…/__init__.py` chain or
`list_envs.py` will not see it. There is currently **one** task: `SoArm100-Reach`.

**Assets are vendored, deliberately.** The SO101 MJCF and meshes are copied into the
package rather than referenced from `../SO-ARM100/`, so cloning `soarm_mjlab` alone is
enough to train — no cross-submodule paths at runtime. Don't "fix" this into a relative
path. Joint names and home pose mirror `soarm_sdk`'s `configs/soarm100.yaml` **1:1**
(`so_arm100_constants.py`: `JOINT_NAMES`, `HOME_KEYFRAME`) so a policy drops onto the
real arm with no name or sign translation — if you change one side, change both.

## Testing and CI

`tests/`: `test_package`, `test_asset_so_arm100`, `test_env_reach`, `test_mdp_reach`,
`test_train_smoke`, `test_push_to_hub`, plus `conftest.py`. All run on CPU
(`FORCE_CPU=1`). This is the best-tested package in the workspace — keep new MDP terms
covered by a `test_mdp_reach`-style unit test plus the env smoke test.

CI (`.github/workflows/ci.yml`): a **blocking `fast` job** (lint + full CPU test
pyramid) on every push/PR, and a **non-blocking `train-smoke` job** running a longer
PPO slice post-merge/on release, uploading the checkpoint as a build artifact.

## Status and docs

Reach has been trained end to end on a rented vast.ai GPU and played back locally —
checkpoint `y4bomfz3`/`model_1499.pt`, ~30% episode success, ~0.04 m position error.
**Deployment (`deploy/reach_policy_runner.py`, ONNX or torch → `RobotInterface`) is
Phase 5 and not implemented yet** — do not describe this package as deployed to
hardware.

- `README.md` — install rationale, deployment argument (Python, not a C++ runtime)
- `docs/vast_ai_training.md` — step-by-step rented-GPU training
- `docs/reach_training_debug_log.md` — full tuning history; read before re-tuning
- `docs/reach_improvement_plan.md`, `docs/v13_goal_perturbation_spec.md`
- root `SOARM_MJLAB_ROADMAP.md` — campaign-level progress
