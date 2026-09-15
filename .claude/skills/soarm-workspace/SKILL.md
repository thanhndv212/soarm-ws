---
name: soarm-workspace
description: 'Cross-package work in soarm-ws: git submodule workflow (bump, pull, status, branch), install order and the three install methods, lint/test/CI per package, changelogs and releases, and the vendored SO-ARM100 hardware assets (URDF/MJCF/STL). Use when a change touches more than one submodule, when bumping a submodule pointer, when setting up the workspace from scratch, or when asked which URDF/MJCF to use.'
---

# SO-ARM Workspace — Cross-Package Operations

_Arguments: name the submodule(s) involved, or say "fresh setup"._

## When to Use

- A change spans two or more submodules, or you need to bump a submodule pointer.
- Fresh clone / new machine setup, or "nothing imports".
- Running lint, tests, or CI for any package; preparing a release.
- Deciding which URDF/MJCF/mesh to reference.

For work *inside* one package, use that package's own skill (see `soarm-start`).
SO-101 calibration specifically is `calibrate`, not this skill.

## The submodule model

`soarm-ws` is an umbrella repo pinning eight submodules, each with its own GitHub
remote (`github.com/thanhndv212/<name>`, except `SO-ARM100` →
`github.com/TheRobotStudio/SO-ARM100`). **Submodules are pinned at specific
commits — you control when to bump.**

```bash
git clone --recurse-submodules <url>                        # clone
git submodule update --remote --recursive                   # pull all to latest remote
git submodule foreach 'echo "--- $name ---" && git status -sb'   # cross-repo status
git submodule foreach git pull                              # cross-repo pull
```

### Changing code in a submodule

```bash
cd <submodule>
git checkout -b my-feature
# edit, commit
git push origin my-feature
cd ..
git add <submodule>                       # bump the pointer in the umbrella repo
git commit -m "bump <submodule> for <reason>"
```

**Cross-package changes are always: bump submodule → re-install → test.** A change
in `soarm_sdk` is not live for `m5teleop`/`soarm_tamp` consumers until the pointer
is bumped and the editable install picks it up (editable src picks up edits live;
re-install only if metadata or entry points changed).

Never push to `SO-ARM100` — it is upstream hardware, read-only.

## Install — order matters

There is **no root `pyproject.toml` or `requirements.txt`**. Install each package
explicitly, and install `soarm_sdk` **first**: `m5teleop` and `soarm_tamp[host]`
declare it as a dependency, so pip will fetch the PyPI copy instead of this
checkout if it is not already installed locally.

```bash
pip install -e soarm_sdk/            # first, always
pip install -e soarm_sdk/[viser]     # + 3-D dashboard (viser, yourdfpy, trimesh)
pip install -e imu_sdk/
pip install -e camera_calibration/
pip install -e m5teleop/
pip install -e soarm_lerobot/
pip install -e soarm_tamp/[host]     # host half only (execute.py)

cd soarm_mjlab && make sync-cpu      # dev machine, no GPU
cd soarm_mjlab && make sync          # GPU box, CUDA 12.8
```

Three install methods coexist: **pip + setuptools** (`imu_sdk`, `m5teleop`,
`camera_calibration`, `soarm_lerobot`), **pip + hatchling** (`soarm_sdk` with `src/`
layout, `soarm_tamp` flat), and **uv** (`soarm_mjlab` only — `mjlab` gates `torch`
behind mutually-exclusive cpu/cu128 extras that pip cannot route).

Dependencies that break without special setup:

| Thing | Why | Fix |
|---|---|---|
| `pinocchio` | pip wheels unreliable; `m5teleop` hard-depends | `conda install -c conda-forge pinocchio` |
| `quadprog` | C extension | `brew install gfortran` on macOS |
| `long_tamp`, `pyhpp` | **not host-installable** | only inside `soarm_tamp/scripts/hpp_container.sh` |
| `uv` | required for `soarm_mjlab` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

## Lint and test — per package, no workspace-wide command

| Package | Lint | Test |
|---|---|---|
| `soarm_sdk` | `hatch run lint:check` | `hatch run test` |
| `soarm_mjlab` | `make lint` | `make test` (`make test-cpu` forces `FORCE_CPU=1`); `make check` = both |
| `camera_calibration` | `ruff check` | `pytest tests/ -v` |
| `m5teleop` | `ruff check` | `pytest tests/ -v` (dry-run path: no hardware, no lerobot, no pinocchio) |
| `imu_sdk`, `soarm_lerobot`, `soarm_tamp` | `ruff check` | **no test suite** |

**Ruff caveat:** `soarm_sdk` pins `select = ["E4","E7","E9","F"]`. Ruff's own
defaults have drifted much wider, so a bare `ruff check` in the other packages
reports hundreds of style findings the workspace never opted into. Read output with
that in mind; do not mass-fix them uninvited.

**CI** exists in two packages only. `soarm_mjlab` — a blocking `fast` job (lint +
CPU test pyramid) on every push/PR, plus a non-blocking `train-smoke` PPO slice
post-merge that uploads a checkpoint artifact; `uv.lock` is committed and CI runs
`uv sync --locked`, so a stale lockfile fails the build. `soarm_sdk` — `ruff check
src tests` + `pytest`, matrixed over Python 3.9–3.12.

No pre-commit hooks at any level. Single author, no branch naming convention.

## Changelogs and licensing

Every first-party submodule has its own `LICENSE` (MIT) and `CHANGELOG.md`, plus a
workspace-level `CHANGELOG.md` at the root. **Check a package's `CHANGELOG.md`
before `git log`-spelunking it** — it is maintained and reconstructed from history.
The whole workspace is MIT (`imu_sdk` and `camera_calibration` were relicensed from
Apache-2.0). `SO-ARM100` carries its own upstream license.

Keep-a-Changelog format, semver. Add an `## [Unreleased]` entry for any
user-visible change in the package you touch, and to the root changelog when the
change is cross-package or workspace-shaped.

## Vendored hardware assets — `SO-ARM100/`

Read-only, from TheRobotStudio. Contains `Simulation/` (URDF + MuJoCo MJCF for
**both** `SO100/` and `SO101/`), `STL/`, `STEP/`, `Mini/`, `Optional/` (wrist cam
mounts for RealSense D435/D405), `Software/`, `docs/`, `media/`.

**Which model to use:** the physical arm is an **SO-101** →
`SO-ARM100/Simulation/SO101/so101_new_calib.urdf`. `soarm_tamp` uses the SO101
revision (via its own `generated/so101.urdf`), `soarm_mjlab` vendors the SO101 MJCF
and meshes into its own package tree so it needs no cross-submodule paths at
runtime. `soarm_sdk`'s viser dashboards and `soarm_tamp`'s plan-and-run dashboard
both default to `SO101/so101_new_calib.urdf` too, mapped through the arm's saved
calibration — there is no remaining live SO100 default in this workspace.

## Standing plans

- `archive/MIGRATION_PLAN.md` — `soarm_sdk` hardening (Part A, done) and the
  deliberately **un-scheduled** `fullstack_manip` migration (Part B). Its standing
  position: do not migrate that kinematics/planning/control stack speculatively —
  none of it has run against real hardware, and `m5teleop` already has a validated
  IK loop. Migrate pieces only when a concrete hardware task needs them. Moved to
  `archive/` since Part A is done and Part B is deliberately gated, not outstanding.
- `archive/TELEMETRY_PLAN.md` — all five phases implemented; kept for history.
- `SOARM_MJLAB_ROADMAP.md` (root, still active) — RL training campaign progress and
  results.
- `README.md` (root) — workspace overview, package table, dashboard screenshots.
- Note `ARCHITECTURE.md` predates `soarm_tamp` and `soarm_mjlab`; its dependency
  graph still describes six packages. `AGENTS.md` is the current one.
