# Temporal WFC LiDAR — Step 3: Age-dependent event hazards

This is a **complete replacement project** containing the Step 1 and Step 2
implementations and tests, extended with a reproducible Step 3 temporal model.

**Goal:** move from constant per-day event hazards to **state-age-dependent
Weibull hazards**, while allowing **shared, dated regional activity regimes**
to change the event rates for several objects. Maintain replay, stable IDs,
query-order independence, and auditable configuration provenance.

> This is a configurable synthetic stochastic process, **not a fitted model of
> real warehouses**. The demonstration numbers are illustrative only.

## Requirements

Python 3.10 or newer; standard library only. **No GPU, pip install, Isaac Sim,
or WFC needed yet.** Run every command from the unzipped project root.

## 1. Verify installation

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

You should see **41 tests** passing, including the original 23 Step 1/2 tests.

## 2. Simulate Step 3's time-dependent world

```bash
PYTHONPATH=src python3 -m temporal_wfc.simulate \
  configs/warehouse_demo.json \
  --temporal-profile configs/temporal_profile_demo.json \
  --days 0 30 180 365 \
  --output-dir outputs/forward
```

The `--temporal-profile` flag turns on the new Weibull/event-window engine.
Without that flag, the **original Step 2 constant-hazard scheduler** is used.

Repeat in reverse time-query order and independently verify the saved records:

```bash
PYTHONPATH=src python3 -m temporal_wfc.simulate \
  configs/warehouse_demo.json \
  --temporal-profile configs/temporal_profile_demo.json \
  --days 365 180 30 0 \
  --output-dir outputs/backward

PYTHONPATH=src python3 -m temporal_wfc.verify \
  configs/warehouse_demo.json outputs/forward \
  --temporal-profile configs/temporal_profile_demo.json

sha256sum outputs/forward/event_ledger.json outputs/backward/event_ledger.json
```

On macOS, use `shasum -a 256` instead of `sha256sum`.
The matching hashes should be identical.

**Observed demonstration for the included seed/config:**

| Sim day | Present objects | Cumulative events |
|---|---:|---:|
| 0 | 5 | 0 |
| 30 | 3 | 5 |
| 180 | 3 | 27 |
| 365 | 3 | 59 |

Do **not** expect the Step 3 history to match the Step 2 event sequence: the
new probabilistic model consumes different random samples and defines a
different world process. But it **must** match between Step 3 forward and
backward queries using the same profile and seed.

## 3. Check the probabilistic model statistically

```bash
PYTHONPATH=src python3 -m temporal_wfc.hazard_stats \
  configs/warehouse_demo.json \
  --temporal-profile configs/temporal_profile_demo.json \
  --object-id box_001 --days 7 30 90 --trials 1000
```

This estimates the probability of an object's **first event** across multiple
independent seeded worlds and compares it with its exact integrated-hazard
probability. Small discrepancies within Monte Carlo sampling uncertainty are
expected. This validates the configured stochastic model, *not* real-world
physical realism.

## 4. How the hazard model works

For event type `e` and a fresh state-sojourn of duration `a` (days):

- `rate = event_rates_per_day[e]` from the initial world JSON;
- `shape = class_shapes[object_class][e]`, optionally overridden by
  `object_shapes[object_uid][e]`, else `default_shape`;
- **baseline cumulative hazard** `H_e(a) = (rate * a)**shape`;
- **baseline instantaneous hazard** `h_e(a) = shape * (rate**shape) * a**(shape-1)`.

If `shape == 1`, this is the Step 2 exponential distribution (constant hazard).
If `shape > 1`, the hazard increases as the object remains unchanged.
If `shape < 1`, the hazard decreases as the object remains unchanged.

The **state-age clock resets after every accepted object event**, including
movement. It is **not** the object's age since installation. For the *first*
event, age begins at Day 0 (or when a replacement object was created).

Each event type has its own independent Exp(1) threshold, and the earliest
threshold-crossing event wins. For a single event type with constant region
multiplier 1:

`P(at least one event by elapsed a) = 1 - exp(-(rate*a)**shape)`.

**Region regimes** in `configs/temporal_profile_demo.json` are half-open
intervals `[start_day, end_day)` that multiply instantaneous event hazards.
They can share a contextual cause across multiple objects (e.g. renovations
in `storage_b`), and their duration is in simulated days. The engine samples
the resulting **piecewise cumulative hazard exactly**, without discretizing
months into simulation frames.

The regime is written to `event_parent_regime` when active at the event time.
The resulting dataset can compare independent rate distributions against
synchronized *rate changes*. However, these are **not actual synchronized
multi-object structural events**. A later step can implement explicit joint
events (`region_reorganize`) and installation arrivals.

## 5. Configuration and provenance

- `configs/warehouse_demo.json`: 5 initial objects, coordinates and baseline
  toy event rates.
- `configs/temporal_profile_demo.json`: class and object Weibull shape settings;
  two example regional windows with named activity and event multipliers.
- `event_ledger.json`: full accepted event history, the exact initial-world
  fingerprint, plus `temporal_profile_sha256` to bind the generated history to
  the stochastic model configuration.
- `world_day_*.json`: snapshots of the same seeded world at requested times.

`verify` for Step 3 requires the original temporal profile and rejects a
mismatched hash. It **replays** the records and compares snapshots; it does not
attempt to infer realistic event rates from LiDAR measurements.

## 6. What Step 3 deliberately does not do

- No collision avoidance, object volumes, accessible paths or WFC constraints.
  A sample can move a forklift through a wall; this is addressed by spatial
  constraint validation and local WFC regeneration **later**.
- No actual scene meshes, RTX LiDAR, sensor visibility or physical trajectories.
- No periodic real-world work shifts or model fitted from long-term datasets.
- No true joint renovation actions or newly installed objects (replacements
  exist, but independent arrivals do not).
- No optimized checkpoints yet; snapshots replay from the Day 0 event history.
- No bitwise consistency guaranteed between different Python RNG
  implementations or after changing model configuration.

## 7. Next: Spatial layout foundation

1. Define modular tile prototypes and boundary connector rules.
2. Generate a small 2D floor-plan grid with spatial WFC (scene geometry later).
3. Validate connectivity, static clearance and fixed persistent chunk IDs.
4. Apply temporal changes through a local spatial constraint resolver and
   report accepted/rejected proposals to measure event-rate distortion.

Do not attempt a large 4D WFC solver as the first spatial integration.
