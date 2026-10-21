"""Generate time-queryable snapshots and an auditable event ledger."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .schema import ContractError, load_world
from .hazards import load_temporal_profile
from .advanced import AgeDependentEvolvingWorld
from .temporal import EvolvingWorld, _time


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate an evolving warehouse at arbitrary elapsed days")
    parser.add_argument("world_file", type=Path)
    parser.add_argument("--days", nargs="+", type=float, default=[0.0, 30.0, 180.0, 365.0])
    parser.add_argument("--temporal-profile", type=Path, default=None,
                        help="Step 3 Weibull shapes and regional event windows")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/demo"))
    args = parser.parse_args()
    try:
        days = [_time(t) for t in args.days]
        profile = load_temporal_profile(args.temporal_profile) if args.temporal_profile else None
        engine = (AgeDependentEvolvingWorld(load_world(args.world_file), profile) if profile
                  else EvolvingWorld(load_world(args.world_file)))
        if len(set(days)) != len(days):
            raise ContractError("--days must not contain duplicate visit times")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for t in days:  # Intentionally preserve user order to exercise replay semantics.
            state = engine.snapshot_at(t)
            filename = args.output_dir / f"world_day_{t:08.3f}.json"
            filename.write_text(json.dumps(asdict(state), indent=2, allow_nan=False) + "\n", encoding="utf-8")
            present = sum(obj.state == "present" for obj in state.objects)
            print(f"Day {t:>5g}: present={present:3d} historical_ids={len(state.objects):3d} "
                  f"events={len(engine.events_up_to(t)):4d} sha256={state.fingerprint()[:16]} file={filename}")

        horizon = max(days)
        ledger_path = args.output_dir / "event_ledger.json"
        ledger = {
            "ledger_schema_version": "0.1.0",
            "world_id": engine.origin.world_id,
            "history_seed": engine.origin.history_seed,
            "origin_fingerprint_sha256": engine.origin.fingerprint(),
            "computed_through_days": horizon,
            "events": [event.to_dict() for event in engine.events_up_to(horizon)],
        }
        if profile:
            ledger["temporal_profile_sha256"] = profile.fingerprint_sha256
        ledger_path.write_text(json.dumps(ledger, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print(f"Event ledger: {ledger_path} ({len(ledger['events'])} accepted events)")
    except (ContractError, OSError, ValueError) as exc:
        parser.exit(1, f"SIMULATION ERROR: {exc}\n")


if __name__ == "__main__":
    main()
