"""Command-line validation for Step 1 sample worlds."""

import argparse
from .schema import ContractError, load_world


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a temporal-WFC world-state file")
    parser.add_argument("world_file", help="Path to a JSON world-state file")
    args = parser.parse_args()
    try:
        world = load_world(args.world_file)
    except (ContractError, OSError, ValueError) as exc:
        parser.exit(1, f"INVALID WORLD: {exc}\n")
    print("VALID WORLD")
    print(f"world_id: {world.world_id}")
    print(f"seed: {world.history_seed}")
    print(f"time_days: {world.time_days:g}")
    print(f"objects: {len(world.objects)}")
    print(f"fingerprint_sha256: {world.fingerprint()}")
    for obj in world.objects:
        print(f"  {obj.object_uid:20} {obj.object_class:12} {obj.state}")


if __name__ == "__main__":
    main()
