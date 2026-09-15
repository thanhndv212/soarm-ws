---
name: soarm-lerobot
description: 'Work in soarm_lerobot — dataset recording and imitation learning for the SO-ARM/SO-101. Use for TeleopRecorder, saving or loading a LeRobotDataset, action chunking, joint normalisation, dataloaders, or ACT / Diffusion Policy training. Read this before promising training works: the soarm-train CLI is a stub — the data pipeline is real, the training loops are not.'
---

# soarm_lerobot — Dataset Recording & Imitation Learning

Path: `soarm_lerobot/` · v0.1.0 · setuptools, flat layout · Python ≥3.10 ·
deps `numpy`, `torch>=2.0`, `lerobot>=0.4`, `datasets` · extras `[train]`
(diffusers, accelerate, wandb), `[dev]` (pytest, ruff)

## State of the package — check this first

**The recording and data pipeline is implemented; the training loops are not.**

| Piece | State |
|---|---|
| `recorder.TeleopRecorder` (216 lines) | real — buffers teleop frames, saves episodes as a `LeRobotDataset` |
| `dataset.py` (221 lines) — `load_dataset`, `compute_joint_stats`, `JointNormalizer`, `ChunkedActionDataset`, `create_dataloader` | real |
| `config.py` | real (63 lines) |
| `soarm-train act` / `soarm-train diffusion` | **stubs.** Both print their hyperparameters and then `"... training not yet implemented."` — a `TODO(build)` in each |
| `soarm-record` | thin wrapper: prints a banner and re-launches `teleop.py --record` |

The root `AGENTS.md`/`ARCHITECTURE.md` describe data "flowing into ACT or Diffusion
Policy training" — that describes the intended path, not working code. **Do not report
a trained policy from this package**; RL training that *does* run end to end lives in
`soarm_mjlab` (see `soarm-mjlab`). Wiring up a real ACT loop is the obvious open task.

`__init__.py` exports only `TeleopRecorder`.

## Recording

Recording happens inside teleop — this package supplies the recorder, not the loop:

```bash
cd m5teleop && python teleop.py --servo-port /dev/cu.usbserial-XXXX --record
# or, equivalently, the wrapper:
soarm-record --repo-id thanhndv212/soarm100-teleop-v1 --task "pick the cube"
```

`soarm-record` flags: `--repo-id` (default `thanhndv212/soarm100-teleop-v1`), `--root`
(default `~/soarm_datasets/<repo-name>`), `--task`, `--fps` (default 50), `--imu-port`,
`--servo-port`, `--dry-run`, `--no-sim`, `--no-rerun`. It forwards them to `teleop.py`
rather than duplicating the main loop — keep that delegation; do not grow a second
control loop here.

**Episodes are delimited by BTN_A** on the M5StickC (the same button that toggles
teleop). Recording runs at 50 Hz to match the control loop.

The import of `TeleopRecorder` in `teleop.py` is wrapped in `try/except ImportError` —
**recording is an optional add-on to teleop, not a hard dependency.** Preserve that:
teleop must keep running for someone who never installed this package.

## The data pipeline

`dataset.py` is what a training loop would consume:

- `load_dataset(...)` — open a `LeRobotDataset` by repo-id/root.
- `compute_joint_stats(ds)` → per-joint mean/std arrays.
- `JointNormalizer` — normalise/denormalise joint vectors from those stats.
- `ChunkedActionDataset` — a `torch.utils.data.Dataset` yielding action chunks
  (the ACT window; `--chunk-size` default 100).
- `create_dataloader(...)` — batching on top.

Training CLI shape, once implemented:
`soarm-train {act,diffusion} --repo-id … [--root --epochs 500 --batch-size 64
--lr 1e-4 --chunk-size 100]`.

## Testing

**No tests** — `tests/` contains only `__init__.py`, and there is no CI. The data
pipeline is pure-`torch`/`numpy` and hardware-free, so it is straightforwardly
testable; adding coverage for `JointNormalizer` and `ChunkedActionDataset` is the
cheapest quality win here. Lint with `ruff check` (see the caveat in
`soarm-workspace`).

## Traps

- Joint values recorded here come through teleop's `ArmInterface`, i.e. **lerobot's
  frame**, not the URDF frame. Anything that later feeds a planner or a sim policy
  needs `soarm_sdk.calibration.frame` — see the joint-frame rule in `soarm-start`.
- `lerobot>=0.4` is a hard dependency here (unlike in `soarm_sdk`, where it is an
  optional extra with a deferred import).
- Changelog: `soarm_lerobot/CHANGELOG.md`.
