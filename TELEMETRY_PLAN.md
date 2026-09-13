# Servo Telemetry Plan

**Status (2026-09-13): all five phases implemented** on `soarm_sdk` branch
`servo-telemetry-block` (329 tests passing, ruff clean). Phases 0-4 are verified
on the arm; phase 5's rigs are unit-tested against a fake arm with planted
backlash and droop, but have not yet been run on hardware — that needs
commanded motion with clearance.

Two deliberate deviations from this plan as first written, both in phase 2:
`ServoSample` has no `read_ok` field (it would have been `True` in every
published sample — a `seq` gap plus the cumulative `read_errors` already say a
read failed), and there is no `telemetry=False` constructor flag (an empty
subscriber list is the same switch with nothing to forget). One thing the plan
did not anticipate: `GroupSyncRead.isAvailable` had to be fixed before the
truncation guard in phase 1 could mean anything — see the changelog.

Goal: one time-aligned stream of *commanded* and *measured* servo state, produced by
whoever owns the bus, consumable by the dashboard, teleop, TAMP and offline analysis
without any of them opening a second serial port.

Motivating use cases, in the order they justify the work:

1. PID tuning (low level) and controller tuning (high level) against real step
   responses rather than one-off ad-hoc reads.
2. Diagnosing why a joint does not follow a valid plan — the failure mode already
   documented at length in `soarm_tamp/README.md`.
3. Characterising backlash and load-dependent elasticity.

## Why not a separate telemetry service

The serial port is exclusive. A standalone process cannot read the bus while teleop,
`soarm_tamp.execute`, or a policy owns it. Any design that opens its own port is
unusable exactly when telemetry matters most — during a real run.

`ServoHardwareInterface` (`soarm_sdk/src/soarm_sdk/robot/hardware.py`) is already the
single bus owner: a background thread at `state_freq` (default 100 Hz) alternating one
`GroupSyncRead` and one `GroupSyncWrite` per tick, with non-blocking
`set_robot_joint_positions`. Telemetry belongs **in that thread**, published
out-of-band. `soarm_tamp` already proved the cross-process half of this pattern with
`<run>/live.jsonl` + `replay.py --follow`: a file is the whole channel.

## Verified on hardware (2026-09-13, SO-101 on /dev/cu.usbmodem5A460827181)

| Claim | Predicted | Measured |
|---|---|---|
| Sync-read 4 B round trip | — | 1.42 ms |
| Sync-read 15 B round trip | — | 2.09 ms |
| Marginal cost of the full block | +0.66 ms | **+0.67 ms** |
| 12 per-servo health reads (dashboard's every-5th poll) | 12-24 ms | **7.36 ms** |

Block offsets match independent per-servo reads exactly for position, voltage
and temperature across all six servos (zero mismatches). ~119 Hz sustained with
zero failed reads over ~10,700 sync-reads. Load sign bit 10 confirmed by driving
the gravity-neutral `shoulder_pan` both ways. Absolute round trips sit ~0.68 ms
above pure wire time at both widths — that constant is the USB turnaround this
design exists to avoid paying twice.

## Bus budget

6 servos, 1 Mbaud, 10 bits/byte. Sync-read instruction is `8 + N` bytes; each servo
replies `6 + L`.

| Transaction | Wire bytes | Time |
|---|---|---|
| Sync-read 4 B (position + speed) — today | 14 + 60 | 0.74 ms |
| Sync-read 15 B (full SRAM telemetry block) | 14 + 126 | 1.40 ms |
| Sync-write PosEx (no replies) | 50 | 0.50 ms |

Full telemetry plus a write is **~1.9 ms/tick, 19% bus duty at 100 Hz**. Bandwidth is
not the constraint; per-transaction USB turnaround is (FTDI latency timer defaults to
16 ms). Hence the rule that governs the whole design: **one transaction per tick, never
a per-servo read in the hot loop.**

## What is streamable

STS3215 read-only SRAM is contiguous 56–70 — one 15-byte block covers everything.

| Addr | Register | B | Unit | Today |
|---|---|---|---|---|
| 56–57 | `PRESENT_POSITION` | 2 | ticks, 15-bit signed | streamed |
| 58–59 | `PRESENT_SPEED` | 2 | ticks/s, signed | streamed |
| 60–61 | `PRESENT_LOAD` | 2 | 0.1% PWM, signed | **misread (1 byte)** |
| 62 | `PRESENT_VOLTAGE` | 1 | 0.1 V | per-servo read only |
| 63 | `PRESENT_TEMPERATURE` | 1 | °C | per-servo read only |
| 65 | `STATUS` | 1 | error flags | unused |
| 66 | `MOVING` | 1 | bool | unused |
| 69–70 | `PRESENT_CURRENT` | 2 | 6.5 mA | **misread (1 byte)** |

Addresses 64, 67, 68 are gaps: read as part of the block, discard. Pair these with the
commanded side already held in-process (goal position, goal speed, `ACC`) and the
EEPROM gains `P`/`I`/`D` at 21/22/23.

## Defects this plan fixes

1. **`ReadLoad` / `ReadCurrent` truncate.** `protocol/sts.py:146,166` call
   `read1ByteTxRx` on 2-byte signed registers. The two registers most useful for
   backlash and elasticity are the two currently unusable.
2. **`JointState.efforts` is always zeros.** `_cached_currents_mA` is allocated
   (`hardware.py:227`) and returned (`:432`) but never written; the sync read is 4
   bytes. Both the class docstring and `get_robot_joint_state`'s docstring claim
   current is read.
3. **Dashboard reopens the port every poll iteration** (`with self.bus(...)` inside
   `_poll_loop`, `dashboard/context.py:160`). Port open costs milliseconds and resets
   the device.
4. **Dashboard stalls every 5th poll.** `_HEALTH_EVERY = 5` triggers 12 per-servo round
   trips (`ReadTemperature` + `ReadCurrent` × 6). At realistic USB turnaround that is a
   12–24 ms hitch, periodically, forever.

## The `_sample_hooks` promotion

`DashboardContext` already has the right idea in the wrong layer. Today:

```python
SampleHook = Callable[[int, Dict[int, int], Dict[int, int]], None]   # context.py:30
for hook in self._sample_hooks:                                       # context.py:218
    hook(poll_count, new_pos, new_spd)
```

Five problems, each of which the promotion should fix rather than carry over:

| Problem | Consequence |
|---|---|
| Hangs off `DashboardContext`, a Viser GUI object | `m5teleop`, `soarm_tamp`, `soarm_mjlab` never build one — the workspace's only telemetry tap is unreachable from the three packages that actually drive the arm |
| Payload is `(count, positions, speeds)` in ticks, **no timestamp** | `recorder.py:34` calls `time.time()` *inside* the hook — wall clock, stamped at hook-invocation not at sample, and an NTP step corrupts a recording |
| Hooks run inline on the poll thread, inside the shared `try:` | one throwing hook aborts the remaining hooks **and** sets `connected=False` / `poll_error` — the UI reports a bus failure that did not happen |
| A slow hook directly extends the poll period | in `ServoHardwareInterface` the same thread also *writes*, so a slow consumer would delay servo commands — a safety issue, not just jitter |
| No unregister | `_build_recorder` registers a closure per panel build; rebuilding leaks hooks appending into dead recording dicts |

Target design, in `soarm_sdk/robot/`:

```python
@dataclass(frozen=True)          # no slots=: package supports Python 3.9
class ServoSample:
    t_mono: float                # time.monotonic() around the txRx, bus thread
    seq: int                     # monotonic; gaps == dropped reads
    ids: Tuple[int, ...]
    position_ticks / position_rad
    velocity_ticks / velocity_rad_s
    load_raw                     # signed, 0.1% PWM duty
    current_mA, voltage_V, temperature_C
    status_flags, moving
    goal_position_ticks / goal_position_rad     # the SAME tick's command
    goal_speed_ticks
    read_ok: bool
    read_errors: int             # cumulative
```

Three decisions worth stating explicitly:

- **Commanded and measured in one record.** This is what makes it a tuning instrument
  instead of a logger: tracking error is a subtraction, and the lag/stiction analysis
  in `soarm_tamp/README.md` becomes a query. Today `execute.py` writes the commanded
  side to `live.jsonl` and the measured side lives nowhere time-aligned with it.
- **The bus thread never calls consumer code.** It appends to a bounded
  `collections.deque(maxlen=…)` (drop-oldest) and sets an `Event`; a publisher thread
  drains it. At 100 Hz × 6 joints a 10 000-sample buffer is ~100 s of history for a few
  MB.
- **`seq` and `read_ok` are part of the contract**, so a consumer can tell "the arm did
  not move" from "we missed the sample".

API: `hw.subscribe() -> TelemetryStream` (drainable, unsubscribable), plus
`hw.telemetry_stats()`. `DashboardContext.add_sample_hook` stays as a thin forwarding
shim over the new stream so `panels/recorder.py` keeps working — consistent with the
SDK's existing deprecation-shim culture.

## Phases

Each phase is independently shippable and leaves the tree green.

### Phase 0 — fix the truncating reads
`protocol/sts.py`: `ReadLoad`, `ReadCurrent` → 2-byte reads with `sts_tohost` sign
decode; check `ReadVoltage`/`ReadTemperature` really are 1 byte (they are).
Tests: byte-fixture decode incl. negative load. No behaviour depends on the old
values, so no migration needed.

### Phase 1 — widen the sync read
`hardware.py`: `GroupSyncRead(self, STS_PRESENT_POSITION_L, 15)`; decode the block in
`_read_once`; populate `_cached_currents_mA` and new caches. `JointState.efforts`
becomes real for the first time. Fix the two stale docstrings.
Cost: +0.66 ms/tick. Tests: fake-packet-handler fixture for the 15-byte block; assert
`efforts` is non-zero given a fixture with current set.

### Phase 2 — the tap
`robot/telemetry.py`: `ServoSample`, ring buffer, `TelemetryStream`, `subscribe()`.
Wire into the bus thread. Off by default (`telemetry=False`) so nothing pays for it
unasked.
Tests: drop-oldest under overflow, `seq` gaps on read failure, subscribe/unsubscribe,
and that a raising consumer cannot affect the producer.

### Phase 3 — sinks
`telemetry/sinks/`: a JSONL sink (same shape as `live.jsonl`) and a rerun sink
(`m5teleop` already depends on `rerun-sdk`). Both run on the publisher thread.
**Never call `rr.connect_grpc(flush_timeout_sec=0.5)` from the bus thread** — see
`m5teleop/viz.py:48`; a 0.5 s flush on a 10 ms tick is fatal.

### Phase 4 — dashboard consumes instead of polls — DONE (`--stream`)
Point `DashboardContext` at a `ServoHardwareInterface` it owns: delete the
open/close-per-iteration, delete `_HEALTH_EVERY` and the 12 per-servo reads (temp and
current now arrive in the block), keep `add_sample_hook` as a shim. Migrate `pid.py`'s
step test — `_compute_step_metrics` at `panels/pid.py:25` already computes rise time
and overshoot from an ad-hoc reader; it should read the shared stream.
This phase is where the user-visible stutter disappears.

Not anticipated when this was written: the poll loop reopens the port every
iteration *so that panels can grab it in between* — 19 `ctx.bus()` call sites
across 5 panels depend on that. Holding the port open therefore required
`ServoHardwareInterface.lend_bus()` (pause the bus thread, lend the handle,
resume) with `ctx.bus()` delegating to it, which leaves all 19 sites unchanged.

### Phase 5 — the diagnostics that motivated this — IMPLEMENTED, NOT YET RUN
- **Backlash**: hysteresis loop — drive to the same commanded position from both
  directions at near-zero load, compare measured. `soarm_tamp/soarm_tamp/joint_test.py
  --single` is already the right rig; point it at the stream.
- **Load-dependent elasticity**: *not observable from the servos alone.* Per
  `soarm_tamp/README.md`, a loaded joint stops 0.03–0.05 rad short while the servo
  reports arrival — about 1 cm at the TCP. The deflection is downstream of whatever the
  encoder sees. Characterise `PRESENT_LOAD` → deflection once against external ground
  truth (`camera_calibration`'s ArUco tooling), then use load as an online predictor.
  That is also the input gravity compensation needs to close that last centimetre.

## Constraints and risks

- **Python 3.9** is the floor for `soarm_sdk` (CI matrixes 3.9–3.12): no `slots=True`,
  no `X | Y` annotations evaluated at runtime, no `match`.
- **Every test stays hardware-free.** Stop at the `PortHandler`/packet-handler boundary
  with the existing fake doubles; no test may require a connected arm.
- **Ruff stays pinned** to `select = ["E4","E7","E9","F"]`. Do not widen it here.
- Phase 1 changes what `efforts` contains for existing consumers — from a silent zero
  to a real value. Grep `soarm_tamp`, `m5teleop`, `soarm_mjlab` for `efforts` before
  landing.
- Phase 4 is the only phase that can regress the dashboard; land it behind a flag and
  keep the old poll loop for one release.
- Add `CHANGELOG.md` entries per package; bump the `soarm_sdk` submodule pointer and
  re-test downstream after Phase 1 and Phase 4 (see `skills/soarm-workspace`).

## Open questions

- Does the STS3215 expose a response-delay register? Not in
  `protocol/registers.py`; if it exists, lowering it raises the achievable tick rate.
- Is 100 Hz enough to see backlash on a fast reversal, or does the characterisation rig
  need a temporary higher `state_freq` with writes disabled?
- Can the USB latency timer be lowered on the adapter in use on macOS? Biggest single
  jitter win if so. (`LATENCY_TIMER = 50` in `protocol/port_handler.py:12` is only the
  timeout budget — it does not set the driver's timer.)
