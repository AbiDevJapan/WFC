"""Verify exported snapshots against a saved event ledger (without re-simulation)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .schema import ContractError, WorldState, load_world
from .hazards import load_temporal_profile
from .temporal import TemporalEvent, replay_events


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify snapshots by replaying exported event history")
    parser.add_argument("world_file", type=Path, help="Initial Day 0 warehouse JSON")
    parser.add_argument("output_dir", type=Path, help="Directory produced by temporal_wfc.simulate")
    parser.add_argument("--temporal-profile", type=Path, default=None,
                        help="Require ledger provenance to match this profile")
    args = parser.parse_args()
    try:
        origin = load_world(args.world_file)
        payload = json.loads((args.output_dir / "event_ledger.json").read_text(encoding="utf-8"))
        if payload.get("world_id") != origin.world_id or payload.get("history_seed") != origin.history_seed:
            raise ContractError("ledger world ID or history seed mismatch")
        if payload.get("origin_fingerprint_sha256") != origin.fingerprint():
            raise ContractError("ledger origin fingerprint mismatch")
        if payload.get("ledger_schema_version") != "0.1.0":
            raise ContractError("unsupported event ledger schema")
        profile_hash = payload.get("temporal_profile_sha256")
        if args.temporal_profile:
            expected_hash = load_temporal_profile(args.temporal_profile).fingerprint_sha256
            if profile_hash != expected_hash:
                raise ContractError("temporal profile hash mismatch")
        elif profile_hash is not None:
            raise ContractError("provide --temporal-profile to verify a Step 3 ledger")
        events = [TemporalEvent.from_dict(e) for e in payload["events"]]
        horizon = payload["computed_through_days"]
        if not isinstance(horizon, (int, float)) or horizon < 0:
            raise ContractError("invalid ledger horizon")
        # Replay the complete history first to validate all event transitions.
        replay_events(origin, events, horizon)
        snapshots = sorted(args.output_dir.glob("world_day_*.json"))
        if not snapshots:
            raise ContractError("no snapshots found")
        for path in snapshots:
            saved = WorldState.parse(json.loads(path.read_text(encoding="utf-8")))
            if saved.time_days > horizon:
                raise ContractError(f"snapshot exceeds ledger horizon: {path.name}")
            reconstructed = replay_events(origin, events, saved.time_days)
            if reconstructed.fingerprint() != saved.fingerprint():
                raise ContractError(f"snapshot mismatch: {path.name}")
            print(f"PASS {path.name} sha256={saved.fingerprint()[:16]}")
        print(f"VERIFIED {len(snapshots)} snapshots and {len(events)} ledger events")
    except (ContractError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"VERIFICATION ERROR: {exc}\n")


if __name__ == "__main__":
    main()
