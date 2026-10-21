# Benchmark contract v0.1 — first implementation step

This is an **initial engineering contract**, not a validated physical model.
It operationalizes the uploaded research proposal's requirement for stable IDs,
queryable time, event provenance, and separation of physical from sensor truth.

## Coordinate / time conventions

- The world frame is `world_enu` (x east, y north, z up), distances in meters; yaw in radians about z.
- The simulator clock is a nonnegative real number of **days since Day 0**.
- Day 30, Day 180, Day 365 are **elapsed durations**, not claims about calendar months.
- Event *intensities* are expressed in **events per day**; the numbers in
  `warehouse_demo.json` are illustrative toy parameters, not measurements.
- Objects have permanent logical `object_uid` identifiers. USD prim paths and
  segmentation IDs are separate implementation identifiers that must later map to these IDs.

## Object state, identity, and events

- `move`: change an object's pose, retain `object_uid`.
- `remove`: object ceases to be physically present, retain its historical ID.
- `replace`: retire the old ID and create a different new ID (even if shape/pose matches).
- `modify`: retain ID; increment `geometry_version` for structural/geometry changes.
- `add`: region-level arrival creates a new ID. It is **not** a hazard on an existing object.
- `region_reorganize`: a correlated regional event that can trigger multiple child events.
- An object may return to its old pose via another `move`; this does not undo its move history.
- `state` indicates **physical presence**, not LiDAR visibility. Absence from a scan
  must never be taken as evidence of physical removal.

## Proposed future event-ledger record (not implemented in this step)

```json
{
  "event_uid": "event_000001",
  "world_id": "warehouse_demo_001",
  "time_days": 18.5,
  "event_type": "move",
  "object_uid": "pallet_001",
  "event_parent_regime": null,
  "before": {"pose": {"x_m": 5, "y_m": 7, "z_m": 0, "yaw_rad": 1.57}},
  "after": {"pose": {"x_m": 6, "y_m": 9, "z_m": 0, "yaw_rad": 1.57}},
  "resolution_status": "accepted"
}
```

Later, the event engine must guarantee that `(world_id, history_seed, time_days)`
yields an identical **physical** state independently of the order of queries.
Use a per-world event ledger and deterministic dedicated random streams.

## Separate world, event and sensor truth

1. **World truth**: complete object state/geometry (implemented only as an initial object registry here).
2. **Event truth**: time-stamped accepted/rejected changes and their causes (future step).
3. **Sensor truth**: LiDAR hits, free-space observations and unknown/occluded locations (later Isaac Sim step).

For sensor truth, reserve distinct states for `observed_occupied`,
`observed_free`, and `unobserved`. `unobserved` does *not* mean removed.

## Scope boundary for Step 1

Included: sample world, versioned schema, validation, canonical serialization,
identity checks and automated tests.

Not included yet: time sampling, temporal snapshots, WFC, collision detection,
3D meshes, Isaac Sim, LiDAR scans or persistence labels.

## Step 1 acceptance check

- Sample JSON passes validation and prints a stable fingerprint.
- Duplicate IDs, negative rates, invalid time units and impossible object birth times fail.
- Reordering objects in JSON does not change canonical state/fingerprint.
