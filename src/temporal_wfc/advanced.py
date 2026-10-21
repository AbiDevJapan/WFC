"""Step 3: Weibull state-age-dependent event engine.

Extends the thoroughly tested Step 2 replay and object change mechanics while
replacing only event scheduling and event-type selection. Spatial validity is
still deliberately out of scope; WFC will supply it in a subsequent phase.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import replace

from .hazards import TemporalProfile
from .schema import ContractError, EVENT_HAZARDS, WorldObject, WorldState
from .temporal import EvolvingWorld, TemporalEvent


class AgeDependentEvolvingWorld(EvolvingWorld):
    def __init__(self, origin: WorldState, profile: TemporalProfile, *, max_events: int = 1_000_000):
        if not isinstance(profile, TemporalProfile):
            raise ContractError('expected TemporalProfile')
        self.profile = profile
        self._planned_type: dict[str, str] = {}
        # EvolvingWorld.__init__ calls overridden _schedule.
        super().__init__(origin, max_events=max_events)

    def _schedule(self, obj: WorldObject, after: float) -> None:
        if obj.state != 'present':
            return
        rng = self._rng_for(obj.object_uid)
        candidates = []
        for event in EVENT_HAZARDS:
            if obj.event_rates_per_day[event] > 0:
                # Each competing cause uses its own independent Exp(1)
                # threshold. The state-age clock resets after each event.
                threshold = rng.expovariate(1.0)
                t = self.profile.next_event_time(obj, event, after, threshold)
                if math.isfinite(t):
                    candidates.append((t, event))
        if not candidates:
            return
        event_time, kind = min(candidates, key=lambda p: (p[0], EVENT_HAZARDS.index(p[1])))
        if event_time <= after:
            raise ContractError('event time must be after current time')
        self._planned_type[obj.object_uid] = kind
        heapq.heappush(self._pending, (event_time, obj.object_uid))

    def _pick_event(self, obj: WorldObject, rng) -> str:
        try:
            return self._planned_type.pop(obj.object_uid)
        except KeyError as exc:
            raise ContractError('missing scheduled event type') from exc

    def _apply(self, t: float, uid: str) -> TemporalEvent:
        region = self._registry[uid].region_id
        regime = self.profile.active_regime(region, t)
        event = super()._apply(t, uid)
        return replace(event, event_parent_regime=regime.name if regime else None)
