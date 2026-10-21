"""Step 2: reproducible continuous-time object events and arbitrary-time replay.

Constant, object-specific *competing* exponential hazards (events/day). The
rates are toy scenarios, not calibrated real warehouse statistics.

Events are generated chronologically, independent of snapshot query order.
Each object uses a derived RNG stream; removing/replacing one object does not
perturb the random sequence of unrelated objects.
"""

from __future__ import annotations

import copy
import hashlib
import heapq
import math
import random
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

from .schema import ContractError, EVENT_HAZARDS, WorldObject, WorldState


@dataclass(frozen=True)
class ObjectChange:
    """One logical object modification, including creations and retirement."""

    object_uid: str
    before: dict[str, Any] | None
    after: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ObjectChange":
        if set(payload) != {"object_uid", "before", "after"}:
            raise ContractError("event change must have object_uid, before, after")
        uid = payload["object_uid"]
        if not isinstance(uid, str) or not uid:
            raise ContractError("event object_uid must be nonempty")
        before, after = payload["before"], payload["after"]
        if before is not None and not isinstance(before, dict):
            raise ContractError("event change before must be object or null")
        if not isinstance(after, dict):
            raise ContractError("event change after must be an object")
        parsed_after = WorldObject.parse(after)
        if parsed_after.object_uid != uid:
            raise ContractError("event change object_uid does not match after")
        if before is not None:
            parsed_before = WorldObject.parse(before)
            if parsed_before.object_uid != uid:
                raise ContractError("event change object_uid does not match before")
        return cls(uid, copy.deepcopy(before), copy.deepcopy(after))


@dataclass(frozen=True)
class TemporalEvent:
    event_uid: str
    world_id: str
    time_days: float
    event_type: str
    object_uid: str
    changes: tuple[ObjectChange, ...]
    resolution_status: str = "accepted"
    event_parent_regime: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["changes"] = [change.to_dict() for change in self.changes]
        return data

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TemporalEvent":
        needed = {"event_uid", "world_id", "time_days", "event_type", "object_uid", "changes", "resolution_status", "event_parent_regime"}
        if set(payload) != needed:
            raise ContractError("event record has incorrect fields")
        t = _time(payload["time_days"])
        if payload["event_type"] not in EVENT_HAZARDS:
            raise ContractError("invalid event_type")
        if payload["resolution_status"] != "accepted":
            raise ContractError("Step 2 event ledger supports only accepted events")
        changes = payload["changes"]
        if not isinstance(changes, list) or not changes:
            raise ContractError("event changes must be a nonempty list")
        for field in ("event_uid", "world_id", "object_uid"):
            if not isinstance(payload[field], str) or not payload[field]:
                raise ContractError(f"invalid event {field}")
        if payload["event_parent_regime"] is not None and (
            not isinstance(payload["event_parent_regime"], str) or not payload["event_parent_regime"].strip()
        ):
            raise ContractError("event_parent_regime must be null or a nonempty string")
        parsed = tuple(ObjectChange.from_dict(ch) for ch in changes)
        if parsed[0].object_uid != payload["object_uid"]:
            raise ContractError("event's first change must target its object_uid")
        if len({ch.object_uid for ch in parsed}) != len(parsed):
            raise ContractError("event contains duplicate object changes")
        if (payload["event_type"] == "replace") != (len(parsed) == 2):
            raise ContractError("replacement requires two changes; other events require one")
        return cls(payload["event_uid"], payload["world_id"], t, payload["event_type"], payload["object_uid"], parsed,
                   payload["resolution_status"], payload["event_parent_regime"])


def _time(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError("time_days must be a finite nonnegative number")
    t = float(value)
    if not math.isfinite(t) or t < 0:
        raise ContractError("time_days must be a finite nonnegative number")
    return t


def _make_snapshot(origin: WorldState, registry: Mapping[str, WorldObject], t: float) -> WorldState:
    data = asdict(origin)
    data["time_days"] = t
    data["objects"] = [asdict(obj) for obj in registry.values()]
    return WorldState.parse(data)


def replay_events(origin: WorldState, events: Iterable[TemporalEvent], time_days: float) -> WorldState:
    """Reconstruct physical truth using only origin + ledger; no RNG needed.

    Strict before/after validation detects corrupted or out-of-order records.
    """
    t = _time(time_days)
    if origin.time_days != 0.0:
        raise ContractError("origin must be a Day 0 world")
    registry: dict[str, WorldObject] = {obj.object_uid: obj for obj in origin.objects}
    previous_time = 0.0
    previous_id = 0
    for event in events:
        if event.time_days > t:
            break
        if event.world_id != origin.world_id:
            raise ContractError("event belongs to another world")
        if event.time_days < previous_time:
            raise ContractError("event ledger is not sorted by event time")
        try:
            event_num = int(event.event_uid.removeprefix("event_"))
        except ValueError as exc:
            raise ContractError("invalid event_uid") from exc
        if event.event_uid != f"event_{event_num:06d}" or event_num != previous_id + 1:
            raise ContractError("event_uids must be sequential")
        previous_id = event_num
        previous_time = event.time_days
        for change in event.changes:
            previous = registry.get(change.object_uid)
            if change.before is None:
                if previous is not None:
                    raise ContractError(f"duplicate creation: {change.object_uid}")
            elif previous is None or asdict(previous) != change.before:
                raise ContractError(f"event replay diverged: {change.object_uid}")
            after = WorldObject.parse(change.after)
            if after.birth_time_days > event.time_days:
                raise ContractError("event creates an object before its birth")
            registry[change.object_uid] = after
    return _make_snapshot(origin, registry, t)


class EvolvingWorld:
    """An in-memory deterministic event history for a fixed initial warehouse.

    The engine extends the same underlying chronological history as time
    queries arrive; older snapshots are always reconstructed by replay.
    """

    def __init__(self, origin: WorldState, *, max_events: int = 1_000_000):
        if origin.time_days != 0.0:
            raise ContractError("EvolvingWorld requires a Day 0 initial state")
        if any(o.state != "present" for o in origin.objects):
            raise ContractError("Day 0 simulation requires objects initially present")
        if isinstance(max_events, bool) or not isinstance(max_events, int) or max_events <= 0:
            raise ContractError("max_events must be a positive integer")
        # Do not allow caller mutation of rate dictionaries to affect history.
        origin_data = asdict(origin)
        origin_data["objects"] = list(origin_data["objects"])
        self.origin = WorldState.parse(origin_data)
        self._max_events = max_events
        self._registry: dict[str, WorldObject] = {o.object_uid: o for o in self.origin.objects}
        self._rngs: dict[str, random.Random] = {}
        self._pending: list[tuple[float, str]] = []
        self._ledger: list[TemporalEvent] = []
        self._computed_through = 0.0
        self._replacement_counter = 0
        for obj in self.origin.objects:
            self._schedule(obj, 0.0)

    def _rng_for(self, uid: str) -> random.Random:
        if uid not in self._rngs:
            text = f"temporal-wfc-step2|{self.origin.world_id}|{self.origin.history_seed}|{uid}"
            seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest(), "big")
            self._rngs[uid] = random.Random(seed)
        return self._rngs[uid]

    def _schedule(self, obj: WorldObject, after: float) -> None:
        if obj.state != "present":
            return
        total = sum(obj.event_rates_per_day[event] for event in EVENT_HAZARDS)
        if total == 0:
            return
        next_t = after + self._rng_for(obj.object_uid).expovariate(total)
        if not math.isfinite(next_t) or next_t <= after:
            raise ContractError("event rate out of supported simulation range")
        heapq.heappush(self._pending, (next_t, obj.object_uid))

    @staticmethod
    def _pick_event(obj: WorldObject, rng: random.Random) -> str:
        rates = obj.event_rates_per_day
        threshold = rng.random() * sum(rates.values())
        cumulative = 0.0
        for event in EVENT_HAZARDS:
            cumulative += rates[event]
            if threshold < cumulative:
                return event
        # Guard floating-point rounding without selecting a zero-probability event.
        return next(event for event in reversed(EVENT_HAZARDS) if rates[event] > 0)

    def _apply(self, t: float, uid: str) -> TemporalEvent:
        obj = self._registry[uid]
        rng = self._rng_for(uid)
        kind = self._pick_event(obj, rng)
        changes: list[ObjectChange] = []
        before = asdict(obj)
        if kind == "move":
            after = copy.deepcopy(before)
            # Step 2 has only a *point-object* bounds check; 3D clearance/WFC
            # constraints are an explicit later milestone.
            after["pose"]["x_m"] = rng.uniform(0, self.origin.width_m)
            after["pose"]["y_m"] = rng.uniform(0, self.origin.height_m)
        elif kind == "modify":
            after = copy.deepcopy(before)
            after["geometry_version"] += 1
        elif kind == "remove":
            after = copy.deepcopy(before)
            after["state"] = "removed"
        elif kind == "replace":
            after = copy.deepcopy(before)
            after["state"] = "removed"
        else:
            raise RuntimeError(f"unknown event type: {kind}")
        updated = WorldObject.parse(after)
        self._registry[uid] = updated
        changes.append(ObjectChange(uid, before, after))
        if kind == "replace":
            self._replacement_counter += 1
            new_uid = f"replacement_{self._replacement_counter:06d}"
            # Avoid conflicts with user IDs without unbounded loops.
            while new_uid in self._registry:
                self._replacement_counter += 1
                new_uid = f"replacement_{self._replacement_counter:06d}"
            created_data = copy.deepcopy(before)
            created_data.update({
                "object_uid": new_uid,
                "birth_time_days": t,
                "geometry_version": 1,
                "state": "present",
            })
            created = WorldObject.parse(created_data)
            self._registry[new_uid] = created
            changes.append(ObjectChange(new_uid, None, created_data))
            self._schedule(created, t)
        elif updated.state == "present":
            self._schedule(updated, t)
        return TemporalEvent(
            event_uid=f"event_{len(self._ledger) + 1:06d}",
            world_id=self.origin.world_id,
            time_days=t,
            event_type=kind,
            object_uid=uid,
            changes=tuple(changes),
        )

    def _extend(self, time_days: float) -> None:
        if time_days <= self._computed_through:
            return
        while self._pending and self._pending[0][0] <= time_days:
            if len(self._ledger) >= self._max_events:
                raise ContractError("max_events limit exceeded; reduce rates or horizon")
            t, uid = heapq.heappop(self._pending)
            self._ledger.append(self._apply(t, uid))
        self._computed_through = time_days

    def snapshot_at(self, time_days: float) -> WorldState:
        t = _time(time_days)
        self._extend(t)
        # All earlier (and later) queries observe one immutable, seeded history.
        return replay_events(self.origin, self._ledger, t)

    def events_up_to(self, time_days: float) -> tuple[TemporalEvent, ...]:
        t = _time(time_days)
        self._extend(t)
        return tuple(copy.deepcopy(e) for e in self._ledger if e.time_days <= t)

    @property
    def simulated_through_days(self) -> float:
        return self._computed_through
