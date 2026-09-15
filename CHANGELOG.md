# Changelog

All notable changes to `soarm-ws` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `LICENSE` (MIT) at the workspace root, and MIT `LICENSE` files in every
  first-party submodule that lacked one: `imu_sdk`, `camera_calibration`,
  `m5teleop`, `soarm_lerobot`, `soarm_tamp`.
- `CHANGELOG.md` in each of those, reconstructed from their git history.
- `README.md` at the workspace root — overview, a package table, a screenshot slot for both
  Viser dashboards (pending real screenshots — see `docs/images/README.md`), a recent-work
  summary, and a link to the project webpage.
- `soarm_tamp` — long-horizon TAMP planning (`long_tamp` on HPP) driving
  the physical SO-101, added as a submodule
  (github.com/thanhndv212/soarm_tamp). Seventh package in the workspace,
  and the first that plans motion rather than recording or executing it.

### Changed

- Moved `MIGRATION_PLAN.md` and `TELEMETRY_PLAN.md` into `archive/` — both are
  fully implemented (Part B of the migration plan is deliberately gated, not
  outstanding work) and were cluttering the root next to the one plan still
  active, `SOARM_MJLAB_ROADMAP.md`.
- **Relicensed `imu_sdk` and `camera_calibration` from Apache-2.0 to
  MIT**, so the whole workspace is MIT. Both had declared Apache-2.0 in
  `pyproject.toml` while shipping no `LICENSE` file; their license
  classifiers were updated to match.
- `m5teleop`, `soarm_lerobot` and `soarm_tamp` now declare `license` and
  `authors` in `pyproject.toml`; previously they declared neither.

### Changed (vendored upstream)

- Bumped `SO-ARM100` from `fda892c` to `eecbe3e`, 8 commits of upstream
  work. Purely additive for us: it brings a wrist-camera variant
  (`so101_new_calib_camera.urdf`/`.xml` plus two meshes), BambuLab A1 mini
  STLs, a LeRobot WebUI 3-point calibration guide, and supplier/doc edits.
  `so101_new_calib.urdf` and the jaw meshes `soarm_tamp` measures its
  gripper geometry from are unchanged, so its constants still hold.

### Notes

- `SO-ARM100` is otherwise untouched. It is TheRobotStudio's upstream
  repo, vendored read-only for its URDF/MJCF models, and already carries
  its own LICENSE and CHANGELOG.
- `soarm_sdk` and `soarm_mjlab` already had MIT LICENSE and CHANGELOG
  files and were left alone.

## [0.1.0] — 2026-07-25

Reconstructed from git history; the workspace root had no changelog before
now. It is a thin umbrella: no root package, no shared `pyproject.toml`, no
build orchestration. Its only job is to pin compatible submodule commits
together and document how they compose.

### Added

- Workspace scaffolding: `AGENTS.md`, `.gitignore`, VS Code config.
- Submodules, in the order they arrived: `soarm_sdk`, `imu_sdk`,
  `m5teleop`, `camera_calibration`, `SO-ARM100`; then `soarm_learn`
  (later `soarm_lerobot`); then `soarm_mjlab`.
- `ARCHITECTURE.md` — how the packages compose, including the two
  independent servo-control stacks (`soarm_sdk` and lerobot's
  `SOFollower`) that talk to the same bus without being layered.
- `MIGRATION_PLAN.md` and `SOARM_MJLAB_ROADMAP.md`.
- Submodule git workflow and session-start protocol in `AGENTS.md`.

### Changed

- Renamed the `soarm_learn` submodule to `soarm_lerobot` throughout.
