"""Step 3: exact time-dependent hazard inversion, replay and regime tests."""

import json
import math
import random
import unittest
from dataclasses import asdict
from pathlib import Path

from temporal_wfc import (AgeDependentEvolvingWorld, TemporalProfile, WorldState,
                          load_temporal_profile, load_world, replay_events)
from temporal_wfc.schema import ContractError
from temporal_wfc.temporal import TemporalEvent

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / 'configs' / 'warehouse_demo.json'
PROFILE = ROOT / 'configs' / 'temporal_profile_demo.json'


def single(rate=0.05, seed=4, region='storage_a', event_type='move'):
    src = json.loads(DEMO.read_text())
    src['history_seed'] = seed
    obj = src['objects'][0]
    obj['region_id'] = region
    obj['event_rates_per_day'] = {e:(rate if e==event_type else 0.0)
                                  for e in ('move','remove','replace','modify')}
    src['objects'] = [obj]
    return WorldState.parse(src)


def profile(shape=2.0, regimes=None, overrides=None):
    return TemporalProfile.parse({
        'temporal_profile_version':'0.1.0',
        'default_shape':shape,
        'class_shapes':overrides or {},
        'object_shapes':{},
        'regimes':regimes or []
    })


def window(start=10, end=20, multiplier=0, kind='move'):
    return {'name':'maintenance','region_id':'storage_a',
            'start_day':start,'end_day':end,'multipliers':{kind:multiplier}}


class ProfileContractTests(unittest.TestCase):
    def test_bad_shapes_are_rejected(self):
        for value in (0,-2,float('nan'),float('inf'),True,9):
            with self.subTest(value=value), self.assertRaises(ContractError):
                profile(value)

    def test_negative_multiplier_overlapping_windows_and_zero_length_rejected(self):
        with self.assertRaisesRegex(ContractError, 'negative'):
            profile(regimes=[window(multiplier=-1)])
        with self.assertRaisesRegex(ContractError, 'overlap'):
            profile(regimes=[window(), window(15,25)])
        with self.assertRaisesRegex(ContractError,'start_day'):
            profile(regimes=[window(20,10)])

    def test_per_class_shape_override_takes_effect(self):
        obj = single().objects[0]
        p = profile(shape=1, overrides={'shelf':{'move':2.2}})
        self.assertEqual(p.shape(obj,'move'),2.2)
        self.assertEqual(p.shape(obj,'modify'),1)

    def test_profile_fingerprint_key_order_invariant(self):
        a = json.loads(PROFILE.read_text())
        b = dict(reversed(list(a.items())))
        self.assertEqual(TemporalProfile.parse(a).fingerprint_sha256,
                         TemporalProfile.parse(b).fingerprint_sha256)


class HazardMathTests(unittest.TestCase):
    def test_uninterrupted_weibull_inverse(self):
        obj = single(rate=0.04).objects[0]
        for k in (0.7,1.0,2.0,4.0):
            p = profile(k)
            threshold = 1.37
            t = p.next_event_time(obj,'move',start=100, exponential_threshold=threshold)
            self.assertAlmostEqual(t,100 + threshold**(1.0/k)/0.04,places=9)

    def test_freeze_window_ignores_suppressed_intensity(self):
        p = profile(1.0,regimes=[window(10,20,0)])
        obj = single(rate=0.1).objects[0]
        # Cumulative hazard at Day 10 = 1. Zero additional hazard until Day 20.
        self.assertAlmostEqual(p.next_event_time(obj,'move',start=0,
                               exponential_threshold=1.5),25.0)
        self.assertAlmostEqual(p.next_event_time(obj,'move',start=0,
                               exponential_threshold=0.5),5.0)

    def test_multiplier_integrates_time_dependent_weibull_correctly(self):
        p = profile(2.0,regimes=[window(10,20,3.0)])
        obj = single(rate=0.1).objects[0]
        # H(10)=(.1*10)^2 = 1.
        # additional H during 10-20 = 3*((.1*20)^2-1)=9.
        self.assertAlmostEqual(p.next_event_time(obj,'move',0,2.5),
                               math.sqrt(1 + (2.5-1)/3)/0.1)
        self.assertAlmostEqual(p.next_event_time(obj,'move',0,11),
                               math.sqrt(4 + (11-10))/0.1)

    def test_regime_half_open_at_window_end(self):
        p = profile(regimes=[window(10,20,5)])
        self.assertIsNone(p.active_regime('storage_a',20))
        self.assertIsNotNone(p.active_regime('storage_a',10))

    def test_empirical_first_event_weibull_distribution(self):
        rate, horizon, shape, trials = 0.03,30,2.0,1200
        p = profile(shape)
        n = sum(bool(AgeDependentEvolvingWorld(single(rate,seed=i),p)
                     .events_up_to(horizon)) for i in range(trials))
        expected = 1 - math.exp(-(rate*horizon)**shape)
        self.assertLess(abs(n/trials - expected),0.05)

    def test_empirical_first_event_with_freeze(self):
        rate, horizon, trials = 0.05,30,1200
        p = profile(1.0,regimes=[window(10,20,0)])
        n = sum(bool(AgeDependentEvolvingWorld(single(rate,seed=i),p)
                     .events_up_to(horizon)) for i in range(trials))
        expected = 1-math.exp(-rate*(horizon-10))
        self.assertLess(abs(n/trials - expected),0.05)


class AdvancedEngineTests(unittest.TestCase):
    def setUp(self):
        self.origin=load_world(DEMO)
        self.profile=load_temporal_profile(PROFILE)

    def test_original_world_unchanged_at_day_zero(self):
        self.assertEqual(AgeDependentEvolvingWorld(self.origin,self.profile).snapshot_at(0).fingerprint(),
                         self.origin.fingerprint())

    def test_reorder_queries_preserves_snapshots_and_ledger(self):
        forward=AgeDependentEvolvingWorld(self.origin,self.profile)
        backward=AgeDependentEvolvingWorld(self.origin,self.profile)
        a={t:forward.snapshot_at(t).fingerprint() for t in (0,30,180,365)}
        b={t:backward.snapshot_at(t).fingerprint() for t in (365,180,30,0)}
        self.assertEqual(a,b)
        self.assertEqual(forward.events_up_to(365),backward.events_up_to(365))

    def test_world_input_object_order_is_independent(self):
        data=asdict(self.origin)
        data['objects'] = list(reversed(data['objects']))
        reordered=WorldState.parse(data)
        a=AgeDependentEvolvingWorld(self.origin,self.profile)
        b=AgeDependentEvolvingWorld(reordered,self.profile)
        self.assertEqual(a.events_up_to(365),b.events_up_to(365))

    def test_regime_attribution_roundtrip_and_replay(self):
        p=profile(1.0,regimes=[window(0,100,6)])
        engine=AgeDependentEvolvingWorld(single(rate=0.4),p)
        event=engine.events_up_to(20)[0]
        self.assertEqual(event.event_parent_regime,'maintenance')
        restored=TemporalEvent.from_dict(event.to_dict())
        self.assertEqual(restored,event)
        self.assertEqual(replay_events(engine.origin,engine.events_up_to(20),20).fingerprint(),
                         engine.snapshot_at(20).fingerprint())

    def test_change_event_type_updates_history_with_replay(self):
        p=profile(1.6)
        origin=single(rate=0.2,event_type='replace')
        engine=AgeDependentEvolvingWorld(origin,p)
        events=engine.events_up_to(90)
        self.assertGreater(len(events),2)
        self.assertEqual(len([o for o in engine.snapshot_at(90).objects if o.state=='present']),1)
        self.assertEqual(replay_events(origin, events,90).fingerprint(),
                         engine.snapshot_at(90).fingerprint())


if __name__ == '__main__':
    unittest.main()

class CumulativeHazardTests(unittest.TestCase):
    def test_integral_piecewise_equals_threshold_sampling_model(self):
        p=profile(2.0,regimes=[window(10,20,3)])
        obj=single(rate=0.1).objects[0]
        self.assertAlmostEqual(p.cumulative_hazard(obj,'move',0,10),1.0)
        self.assertAlmostEqual(p.cumulative_hazard(obj,'move',0,20),10.0)
        self.assertAlmostEqual(p.cumulative_hazard(obj,'move',0,30),15.0)
