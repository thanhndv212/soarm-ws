# skills/

Agent skills for this workspace — one per submodule, a router, a cross-package skill,
and a dedicated calibration skill. They exist so a session can find the right context
without re-deriving the workspace layout by grepping.

| Skill | Covers |
|---|---|
| `soarm-start` | **Router — start here.** Maps the eight submodules, dispatches to the rest. |
| `soarm-workspace` | Submodules, install order, lint/test/CI, changelogs, `SO-ARM100/` assets |
| `soarm-sdk` | `soarm_sdk/` — servo transport, `RobotInterface`, tick↔URDF frame, dashboard |
| `calibrate` | SO-101 tick-to-URDF-frame calibration through `soarm-dashboard-calibration`: reference-pose zeroing, ROM measurement, acceptance tolerances, safety gates |
| `soarm-imu-sdk` | `imu_sdk/` — IMU reader + Arduino firmware |
| `soarm-m5teleop` | `m5teleop/` — the 50 Hz teleoperation loop |
| `soarm-camera-calibration` | `camera_calibration/` — intrinsics + ArUco |
| `soarm-lerobot` | `soarm_lerobot/` — dataset recording, imitation learning |
| `soarm-mjlab` | `soarm_mjlab/` — RL training in MuJoCo (uv, not pip) |
| `soarm-tamp` | `soarm_tamp/` — TAMP planning + hardware execution, plan-and-run dashboard |

## Mirroring

This directory is mirrored, file-for-file, into `.claude/skills/` and `.github/skills/`
so both Claude Code and other tooling that expects `.github/skills/` discover the same
skills without a symlink. **Edit files here (`skills/`) and copy the same change into
both mirrors in the same commit** — there is no longer a symlink keeping them in sync
automatically; a stale mirror is a bug.

```bash
diff -rq skills .claude/skills    # should print nothing
diff -rq skills .github/skills    # should print nothing
```

## Conventions

- One directory per skill, containing `SKILL.md` with YAML frontmatter: `name`
  (must match the directory) and `description`.
- The `description` is the only thing read at discovery time — front-load the
  trigger words a user would actually type.
- Keep skills **factual about state**, including what is *not* implemented
  (`soarm-lerobot`'s training stubs, `soarm-mjlab`'s unimplemented deploy phase).
  A skill that overstates readiness is worse than no skill.
- Point at the in-repo doc rather than duplicating it; `soarm_tamp/README.md` and
  `m5teleop/IMPLEMENTATION.md` stay the sources of truth for their packages.
- When a package's structure, entry points, or status change, update its skill (and
  both mirrors) in the same commit.
