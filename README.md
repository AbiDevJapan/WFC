# Temporal WFC LiDAR — Step 1 starter

First deliverable for *Time-Conditioned Procedural Generation of Evolving 3D
Environments for Long-Term LiDAR Mapping*.

**Goal:** freeze an initial world/object contract before writing time-dependent
change scheduling or integrating WFC/Isaac Sim.

## Requirements

Python 3.10+ (no pip dependencies in Step 1).

## Run (macOS zsh, Linux bash)

From the project root:

```bash
PYTHONPATH=src python3 -m temporal_wfc.validate configs/warehouse_demo.json
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Expected: `VALID WORLD`, five registered objects, a SHA-256 fingerprint,
and seven passing tests.

## Contents

- `configs/warehouse_demo.json` — one 20 m × 20 m **abstract** warehouse state
  with illustrative event intensities. No 3D geometry or physics.
- `src/temporal_wfc/schema.py` — typed objects, validation and canonical hashing.
- `src/temporal_wfc/validate.py` — run validation and inspect identities.
- `tests/test_schema.py` — tests for identities, units and consistent serialization.
- `docs/benchmark_contract.md` — time, identity, event and annotation semantics.

## Next development task

Build the seeded continuous-time event scheduler and event ledger. Test
Day 180 → Day 30 and Day 30 → Day 180 query ordering for exact replay.
