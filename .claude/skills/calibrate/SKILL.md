---
name: calibrate
description: Calibrate an SO-101 arm through the soarm_sdk Viser workflow with explicit acceptance tolerances, provenance, and safety gates.
---

# SO-ARM calibration

Use this skill for SO-101 tick-to-URDF-frame calibration. Calibration belongs
to `soarm_sdk`; do not add calibration actions to `soarm_tamp`.

## Safety rules

- Do not command a physical arm until the operator confirms the arm is clear,
  supported where required, and the selected joint is safe to move.
- Treat raw ticks, lerobot-normalized values, and URDF radians as distinct
  frames. State the frame for every value.
- Never infer a zero from ROM-sweep midpoint on an asymmetric mechanism.
- Never mark a joint `reference_pose` unless the selected pose explicitly
  covers that joint.
- Require explicit per-arm acceptance tolerances. No code path may infer
  one: a calibration that recorded none has none, and stays blocked. The
  dashboard pre-fills suggested starting values (3 deg pose repeatability,
  3 deg model deviation, 30 tick ROM repeatability) for the operator to
  review and commit — a form default, never a fallback.
- Preserve the prior saved calibration when a validation step fails.

## Launch

```bash
soarm-dashboard-calibration --device /dev/cu.usbmodemXXXX --stream
```

The dashboard guides these stages and persists the accepted evidence in the
calibration file.

## Procedure

The Calibration tab is one linear pass: a *Live arm state* panel, then six
numbered step folders. The acceptance record in **Step 6** grades the evidence
each step produces and labels every row with the step that produces it, so a
BLOCKED row names the folder to reopen. The stages below cite those folders.

0. **Load and inspect.** *(Live arm state — not a numbered folder.)* Confirm
   the SO-101 URDF, calibration path, arm ID, and servo IDs. Connect and
   confirm the 3-D mirror has live readings. The acceptance record renders
   without an arm attached, so the blocked stages can be read before
   connecting.
1. **Record acceptance tolerances.** *(Tab 1.)* The operator must explicitly
   set: reference-pose repeatability in URDF radians/degrees, model-deviation
   watchdog threshold, and ROM endpoint repeatability in ticks. The fields
   start at 3 deg / 3 deg / 30 ticks; treat those as a starting point to
   review, not as approved values. Save only after the operator approves
   these task-specific values. Nothing downstream
   can be graded until these exist, which is why it is first.
2. **Verify direction signs.** *(Step 2.)* Jog one joint at a time by a small
   safe amount and have the operator confirm the physical and URDF model
   motions match. Record the check with **Confirm signs verified**, naming
   what was actually done — that note is the only lasting record of it. A
   mismatch requires fixing the sign in the file and re-pinning the affected
   zero at stage 4.
3. **Measure ROM.** *(Step 3.)* Run an automatic sweep only with clearance and
   operator approval, or record endpoints manually. Store `tick_min`/
   `tick_max` as hardware facts; do not change zero offsets from their
   midpoint.
4. **Pin reference-pose zeros.** *(Step 4.)* The symmetry cross-check that
   opens the folder is a hypothesis about the hard stops, not a measurement —
   use it only to choose which joints to chase. Then select a named pose,
   physically establish it, wait for stability, and capture multiple samples.
   Re-zero only joints in that pose's `covers` list. `folded_flat` covers
   `shoulder_lift` and `elbow_flex` only.
5. **Nudge a single zero.** *(Step 5, optional.)* Only when stage 4 left one
   member visibly off, and only against an independent measurement. A nudge
   discards that joint's pose provenance, so stage 6 grades it on what
   remains. Prefer re-pinning a pose.
6. **Review the report.** *(Step 6.)* It must pass explicit tolerances, signs,
   ROM, zero-source provenance, and reference-pose repeatability. Resolve
   every blocked stage; never waive it by relabeling provenance.
7. **Save and archive.** *(Step 6.)* The dashboard creates a backup before
   writing the accepted calibration, and refuses to write while any row is
   BLOCKED. Record calibration path, arm ID, URDF revision, timestamp, pose,
   samples, and tolerance values in the final report.
8. **Use in TAMP.** TAMP consumes the saved calibration read-only. Its
   Execution Watchdog may block planning/execution for large model/file or
   real-arm/planning-bound deviations; return to this SDK workflow to fix
   calibration.

## Automated versus human steps

Automate ROM measurement, stability sampling, validation, provenance capture,
backup, reporting, and effective-bound calculations. Keep an operator in the
loop for sign semantics, physical reference-pose placement, and safety
clearance approval.
