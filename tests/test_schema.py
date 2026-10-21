"""Standard-library tests: python -m unittest discover -s tests -v."""

import copy
import json
import unittest
from pathlib import Path

from temporal_wfc.schema import ContractError, WorldState, load_world


DEMO = Path(__file__).resolve().parents[1] / "configs" / "warehouse_demo.json"


class WorldContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with DEMO.open(encoding="utf-8") as f:
            cls.payload = json.load(f)

    def test_sample_world_valid(self):
        world = load_world(DEMO)
        self.assertEqual(world.time_days, 0.0)
        self.assertEqual(len(world.objects), 5)
        self.assertEqual(len({o.object_uid for o in world.objects}), 5)

    def test_same_world_same_fingerprint_regardless_of_object_order(self):
        first = WorldState.parse(self.payload)
        reversed_data = copy.deepcopy(self.payload)
        reversed_data["objects"].reverse()
        second = WorldState.parse(reversed_data)
        self.assertEqual(first.fingerprint(), second.fingerprint())
        self.assertEqual(first.canonical_json(), second.canonical_json())

    def test_duplicate_identity_rejected(self):
        invalid = copy.deepcopy(self.payload)
        invalid["objects"][1]["object_uid"] = invalid["objects"][0]["object_uid"]
        with self.assertRaisesRegex(ContractError, "unique"):
            WorldState.parse(invalid)

    def test_negative_event_rate_rejected(self):
        invalid = copy.deepcopy(self.payload)
        invalid["objects"][0]["event_rates_per_day"]["move"] = -0.01
        with self.assertRaisesRegex(ContractError, "nonnegative"):
            WorldState.parse(invalid)

    def test_mismatched_time_unit_rejected(self):
        invalid = copy.deepcopy(self.payload)
        invalid["time_unit"] = "months"
        with self.assertRaisesRegex(ContractError, "time_unit"):
            WorldState.parse(invalid)

    def test_object_with_future_birth_rejected(self):
        invalid = copy.deepcopy(self.payload)
        invalid["objects"][0]["birth_time_days"] = 7.0
        with self.assertRaisesRegex(ContractError, "birth time"):
            WorldState.parse(invalid)

    def test_nonfinite_pose_rejected(self):
        invalid = copy.deepcopy(self.payload)
        invalid["objects"][0]["pose"]["x_m"] = float("nan")
        with self.assertRaisesRegex(ContractError, "finite"):
            WorldState.parse(invalid)


if __name__ == "__main__":
    unittest.main()
