"""Step 2 temporal sampling and replay behavior (no simulator dependencies)."""

import copy
import json
import math
import random
import unittest
from dataclasses import asdict
from pathlib import Path

from temporal_wfc.schema import ContractError, WorldState, load_world
from temporal_wfc.temporal import EvolvingWorld, TemporalEvent, replay_events


DEMO = Path(__file__).resolve().parents[1] / "configs" / "warehouse_demo.json"


def single_object(move=0.0, remove=0.0, replace=0.0, modify=0.0, seed=11):
    payload = json.loads(DEMO.read_text(encoding="utf-8"))
    payload["objects"] = [payload["objects"][0]]
    payload["history_seed"] = seed
    payload["objects"][0]["event_rates_per_day"] = dict(
        move=move, remove=remove, replace=replace, modify=modify
    )
    return WorldState.parse(payload)


class TemporalEngineTests(unittest.TestCase):
    def setUp(self):
        self.origin = load_world(DEMO)

    def test_day_zero_snapshot_equals_origin(self):
        engine = EvolvingWorld(self.origin)
        self.assertEqual(engine.snapshot_at(0).fingerprint(), self.origin.fingerprint())
        self.assertEqual(engine.events_up_to(0), ())

    def test_time_query_order_invariance(self):
        forward = EvolvingWorld(self.origin)
        a30 = forward.snapshot_at(30).fingerprint()
        a180 = forward.snapshot_at(180).fingerprint()
        a365 = forward.snapshot_at(365).fingerprint()
        backward = EvolvingWorld(self.origin)
        b365 = backward.snapshot_at(365).fingerprint()
        b180 = backward.snapshot_at(180).fingerprint()
        b30 = backward.snapshot_at(30).fingerprint()
        self.assertEqual((a30, a180, a365), (b30, b180, b365))
        self.assertEqual([e.to_dict() for e in forward.events_up_to(365)],
                         [e.to_dict() for e in backward.events_up_to(365)])

    def test_repeat_seed_same_events_and_different_seed_differs(self):
        a = EvolvingWorld(self.origin)
        b = EvolvingWorld(self.origin)
        self.assertEqual(a.snapshot_at(365).fingerprint(), b.snapshot_at(365).fingerprint())
        self.assertEqual(a.events_up_to(365), b.events_up_to(365))
        modified = asdict(self.origin)
        modified["objects"] = list(modified["objects"])
        modified["history_seed"] += 1
        other = EvolvingWorld(WorldState.parse(modified))
        self.assertNotEqual([e.to_dict() for e in a.events_up_to(365)],
                            [e.to_dict() for e in other.events_up_to(365)])

    def test_replay_saved_ledger_without_rng(self):
        engine = EvolvingWorld(self.origin)
        expected = engine.snapshot_at(365).fingerprint()
        payload = json.dumps([e.to_dict() for e in engine.events_up_to(365)])
        loaded = [TemporalEvent.from_dict(v) for v in json.loads(payload)]
        replayed = replay_events(self.origin, loaded, 365)
        self.assertEqual(expected, replayed.fingerprint())
        self.assertEqual(engine.snapshot_at(30).fingerprint(),
                         replay_events(self.origin, loaded, 30).fingerprint())

    def test_event_timestamps_sorted_and_after_states_consistent(self):
        engine = EvolvingWorld(self.origin)
        events = engine.events_up_to(365)
        self.assertGreater(len(events), 0)
        self.assertEqual([e.event_uid for e in events],
                         [f"event_{i:06d}" for i in range(1, len(events) + 1)])
        self.assertEqual([e.time_days for e in events],
                         sorted(e.time_days for e in events))
        self.assertTrue(all(0 < e.time_days <= 365 for e in events))
        self.assertTrue(all(e.resolution_status == "accepted" for e in events))
        for e in events:
            self.assertEqual(e.changes[0].object_uid, e.object_uid)

    def test_negative_nonfinite_and_boolean_time_rejected(self):
        engine = EvolvingWorld(self.origin)
        for invalid in (-1, float("nan"), float("inf"), True):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ContractError):
                    engine.snapshot_at(invalid)

    def test_zero_rates_produce_no_events(self):
        origin = single_object()
        engine = EvolvingWorld(origin)
        self.assertEqual(engine.events_up_to(5000), ())
        self.assertEqual(len(engine.snapshot_at(5000).objects), 1)
        self.assertEqual(engine.snapshot_at(5000).objects[0].pose, origin.objects[0].pose)

    def test_move_retains_uid_and_remains_in_world_bounds(self):
        origin = single_object(move=2)
        engine = EvolvingWorld(origin)
        snap = engine.snapshot_at(10)
        self.assertGreater(len(engine.events_up_to(10)), 5)
        for event in engine.events_up_to(10):
            self.assertEqual(event.event_type, "move")
            self.assertEqual(event.changes[0].object_uid, origin.objects[0].object_uid)
        self.assertEqual(len(snap.objects), 1)
        x, y = snap.objects[0].pose.x_m, snap.objects[0].pose.y_m
        self.assertTrue(0 <= x <= origin.width_m)
        self.assertTrue(0 <= y <= origin.height_m)

    def test_remove_stops_future_events_but_keeps_historical_id(self):
        origin = single_object(remove=10)
        engine = EvolvingWorld(origin)
        snap = engine.snapshot_at(365)
        events = engine.events_up_to(365)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "remove")
        self.assertEqual(len(snap.objects), 1)
        self.assertEqual(snap.objects[0].state, "removed")

    def test_modify_increments_geometry_version(self):
        origin = single_object(modify=1.0)
        engine = EvolvingWorld(origin)
        state = engine.snapshot_at(10)
        self.assertEqual(state.objects[0].geometry_version,
                         origin.objects[0].geometry_version + len(engine.events_up_to(10)))

    def test_replace_retires_old_id_and_creates_new_id(self):
        origin = single_object(replace=1.0)
        engine = EvolvingWorld(origin)
        state = engine.snapshot_at(10)
        events = engine.events_up_to(10)
        self.assertGreater(len(events), 0)
        self.assertTrue(all(e.event_type == "replace" for e in events))
        self.assertTrue(all(len(e.changes) == 2 for e in events))
        self.assertEqual(len(state.objects), len(events) + 1)
        present = [o for o in state.objects if o.state == "present"]
        self.assertEqual(len(present), 1)
        self.assertEqual(next(o for o in state.objects if o.object_uid == "shelf_001").state,
                         "removed")
        self.assertNotEqual(present[0].object_uid, "shelf_001")
        self.assertGreater(present[0].birth_time_days, 0)

    def test_record_corruption_is_detected_by_replay(self):
        engine = EvolvingWorld(single_object(modify=1))
        ledger = [e.to_dict() for e in engine.events_up_to(10)]
        self.assertGreater(len(ledger), 0)
        ledger[0]["changes"][0]["before"]["geometry_version"] = 999
        corrupted = [TemporalEvent.from_dict(e) for e in ledger]
        with self.assertRaisesRegex(ContractError, "diverged"):
            replay_events(engine.origin, corrupted, 10)

    def test_world_object_order_does_not_change_generated_events(self):
        payload = asdict(self.origin)
        payload["objects"] = list(payload["objects"])
        random.Random(12).shuffle(payload["objects"])
        scrambled = WorldState.parse(payload)
        first = EvolvingWorld(self.origin)
        second = EvolvingWorld(scrambled)
        self.assertEqual(first.snapshot_at(365).fingerprint(),
                         second.snapshot_at(365).fingerprint())
        self.assertEqual(first.events_up_to(365), second.events_up_to(365))

    def test_statistical_probability_of_first_move(self):
        # For a constant movement hazard, first movement follows Exp(lambda).
        # Conservative tolerance for an engineering regression test, not a
        # claim that these event rates match a real warehouse.
        horizon, rate, trials = 30, 0.04, 1200
        simulated = sum(bool(EvolvingWorld(single_object(move=rate, seed=k))
                             .events_up_to(horizon)) for k in range(trials)) / trials
        expected = 1 - math.exp(-rate * horizon)
        self.assertLess(abs(simulated - expected), 0.045)


if __name__ == "__main__":
    unittest.main()
