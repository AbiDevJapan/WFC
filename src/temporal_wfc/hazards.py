"""Step 3: time-dependent competing hazards and scheduled shared regional regimes.

Each event type has a Weibull *state-sojourn* hazard.  The clock resets after
any accepted object event (including move); it is not the object's birth age.
For rate r > 0 per day and shape k > 0, integrated baseline intensity from
state age 0 to age a is (r * a)**k.  k=1 recovers constant rate r.

Regional regimes are externally configured, fixed-time intervals. They multiply
an event's hazard throughout that interval, so multiple objects in a region
experience related time-dependent intensities. These are *not* direct joint
renovation events, which belong in a later phase.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .schema import ContractError, EVENT_HAZARDS, WorldObject


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f'{label} must be a JSON object')
    return value


def _real(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f'{label} must be a finite number')
    v = float(value)
    if not math.isfinite(v) or (positive and v <= 0):
        raise ContractError(f'{label} must be a finite {"positive" if positive else "number"}')
    return v


def _shapes(value: Any, label: str) -> dict[str, float]:
    m = _object(value, label)
    if set(m) - set(EVENT_HAZARDS):
        raise ContractError(f'{label} contains invalid event types')
    parsed = {event: _real(v, f'{label}.{event}', positive=True) for event,v in m.items()}
    if any(v > 8 for v in parsed.values()):
        raise ContractError(f'{label}: Weibull shape must not exceed 8')
    return parsed


@dataclass(frozen=True)
class Regime:
    name: str
    region_id: str
    start_day: float
    end_day: float
    multipliers: dict[str, float]

    def multiplier(self, event_type: str) -> float:
        return self.multipliers.get(event_type, 1.0)


@dataclass(frozen=True)
class TemporalProfile:
    default_shape: float
    class_shapes: dict[str, dict[str, float]]
    object_shapes: dict[str, dict[str, float]]
    regimes: tuple[Regime, ...]
    fingerprint_sha256: str

    @classmethod
    def parse(cls, data: Any) -> 'TemporalProfile':
        m = _object(data, 'temporal profile')
        required = {'temporal_profile_version', 'default_shape', 'class_shapes', 'object_shapes', 'regimes'}
        if set(m) != required or m['temporal_profile_version'] != '0.1.0':
            raise ContractError('unsupported temporal profile format or missing fields')
        default = _real(m['default_shape'], 'default_shape', positive=True)
        if default > 8:
            raise ContractError('default_shape must not exceed 8')
        by_class = {k: _shapes(v, f'class_shapes.{k}') for k,v in _object(m['class_shapes'], 'class_shapes').items()}
        by_object = {k: _shapes(v, f'object_shapes.{k}') for k,v in _object(m['object_shapes'], 'object_shapes').items()}
        if not all(isinstance(k,str) and k.strip() for k in (*by_class, *by_object)):
            raise ContractError('shape override keys must be nonempty strings')
        if not isinstance(m['regimes'], list):
            raise ContractError('regimes must be a list')
        regimes: list[Regime] = []
        for i,item in enumerate(m['regimes']):
            r = _object(item, f'regime[{i}]')
            if set(r) != {'name','region_id','start_day','end_day','multipliers'}:
                raise ContractError(f'regime[{i}] has incorrect fields')
            if not all(isinstance(r.get(k),str) and r[k].strip() for k in ('name','region_id')):
                raise ContractError(f'regime[{i}] name and region_id must be nonempty strings')
            start = _real(r['start_day'], f'regime[{i}].start_day')
            end = _real(r['end_day'], f'regime[{i}].end_day')
            if start < 0 or end <= start:
                raise ContractError(f'regime[{i}] requires 0 <= start_day < end_day')
            values = _object(r['multipliers'],f'regime[{i}].multipliers')
            if set(values) - set(EVENT_HAZARDS):
                raise ContractError('regime has invalid event multiplier keys')
            multipliers = {key: _real(v, f'regime[{i}].{key}') for key,v in values.items()}
            if any(v < 0 for v in multipliers.values()):
                raise ContractError('regime multipliers cannot be negative')
            regimes.append(Regime(r['name'], r['region_id'], start, end, multipliers))
        regimes.sort(key=lambda r:(r.region_id,r.start_day,r.name))
        previous: dict[str, Regime] = {}
        for r in regimes:
            prior = previous.get(r.region_id)
            if prior is not None and prior.end_day > r.start_day:
                raise ContractError('regional regimes may not overlap within the same region')
            previous[r.region_id] = r
        canonical = json.dumps(m, sort_keys=True, separators=(',', ':'), allow_nan=False)
        return cls(default, by_class, by_object, tuple(regimes),
                   hashlib.sha256(canonical.encode()).hexdigest())

    def shape(self, obj: WorldObject, event: str) -> float:
        return (self.object_shapes.get(obj.object_uid, {}).get(event,
                self.class_shapes.get(obj.object_class, {}).get(event,
                self.default_shape)))

    def region_regimes(self, region_id: str) -> tuple[Regime, ...]:
        return tuple(r for r in self.regimes if r.region_id == region_id)

    def active_regime(self, region_id: str, t: float) -> Regime | None:
        return next((r for r in self.regimes if r.region_id == region_id and
                     r.start_day <= t < r.end_day), None)

    def _windows(self, region_id: str, start_time: float):
        """Yield [start,end) segments with one effective regional regime."""
        boundaries = sorted({start_time} | {
            t for r in self.region_regimes(region_id)
            for t in (r.start_day, r.end_day) if t > start_time
        })
        for i, left in enumerate(boundaries):
            right = boundaries[i + 1] if i + 1 < len(boundaries) else math.inf
            # A left endpoint belongs to a regime starting there; an ending
            # regime is inactive from that time forward.
            yield left, right, self.active_regime(region_id, left)

    def cumulative_hazard(self, obj: WorldObject, event: str, start: float, end: float) -> float:
        """Exact integrated event intensity over [start, end] since last event.

        The state-age clock is reset at ``start``; this gives the theoretical
        first-event survival used for Monte-Carlo validation.
        """
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
            raise ContractError('invalid cumulative hazard time interval')
        rate = obj.event_rates_per_day[event]
        if rate == 0:
            return 0.0
        shape = self.shape(obj, event)
        total = 0.0
        for left, right, regime in self._windows(obj.region_id, start):
            if left >= end:
                break
            right = min(right, end)
            multiplier = regime.multiplier(event) if regime else 1.0
            total += multiplier * ((rate * (right-start)) ** shape -
                                   (rate * (left-start)) ** shape)
        return total

    def next_event_time(self, obj: WorldObject, event: str, start: float,
                        exponential_threshold: float) -> float:
        """Invert integrated hazard across piecewise multiplier windows exactly.

        exponential_threshold must be an independent Exp(1) random sample.
        The object's state-age clock is zero at ``start``.
        """
        rate = obj.event_rates_per_day[event]
        if rate == 0:
            return math.inf
        shape = self.shape(obj, event)
        remaining = exponential_threshold
        if remaining <= 0 or not math.isfinite(remaining):
            raise ContractError('threshold must be positive and finite')
        for left, right, regime in self._windows(obj.region_id, start):
            multiplier = regime.multiplier(event) if regime else 1.0
            if multiplier == 0:
                continue
            age_start = left - start
            baseline_start = (rate * age_start) ** shape
            if math.isinf(right):
                integrated = math.inf
            else:
                age_end = right - start
                integrated = multiplier * ((rate * age_end) ** shape - baseline_start)
            if remaining <= integrated:
                new_baseline = baseline_start + remaining / multiplier
                absolute_age = new_baseline ** (1.0 / shape) / rate
                t = start + absolute_age
                if not math.isfinite(t) or t <= start:
                    raise ContractError('hazard event time outside numerical range')
                # Floating-point noise at a window boundary should not move
                # the event beyond the integrated-hazard interval.
                if math.isfinite(right) and t > right and t - right > 1e-8 * max(1.0,right):
                    raise ContractError('hazard inversion exceeded regime window')
                return min(t, right)
            remaining -= integrated
        return math.inf


def load_temporal_profile(path: str | Path) -> TemporalProfile:
    return TemporalProfile.parse(json.loads(Path(path).read_text(encoding='utf-8')))
