"""Step 1: a deterministic, simulator-independent persistent-world contract.

All event rates in this module are illustrative input parameters in units
of events per *simulated day*. This module does not simulate events.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "0.1.0"
EVENT_HAZARDS = ("move", "remove", "replace", "modify")
ALLOWED_STATES = ("present", "removed")


class ContractError(ValueError):
    """Raised when a world file violates the versioned dataset contract."""


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be a JSON object")
    return value


def _nonblank(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a nonempty string")
    return value


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{label} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ContractError(f"{label} must be finite")
    return result


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractError(f"{label} must be an integer >= {minimum}")
    return value


@dataclass(frozen=True)
class Pose:
    x_m: float
    y_m: float
    z_m: float
    yaw_rad: float

    @classmethod
    def parse(cls, source: Any, label: str) -> "Pose":
        m = _mapping(source, label)
        required = ("x_m", "y_m", "z_m", "yaw_rad")
        if set(m) != set(required):
            raise ContractError(f"{label} requires exactly {required}")
        return cls(*(_finite_number(m[k], f"{label}.{k}") for k in required))


@dataclass(frozen=True)
class WorldObject:
    object_uid: str
    object_class: str
    asset_key: str
    region_id: str
    geometry_version: int
    birth_time_days: float
    state: str
    pose: Pose
    event_rates_per_day: dict[str, float]

    @classmethod
    def parse(cls, source: Any) -> "WorldObject":
        m = _mapping(source, "object")
        uid = _nonblank(m.get("object_uid"), "object_uid")
        rates = _mapping(m.get("event_rates_per_day"), f"{uid}.event_rates_per_day")
        if set(rates) != set(EVENT_HAZARDS):
            raise ContractError(f"{uid}: event rates must specify exactly {EVENT_HAZARDS}")
        parsed_rates = {
            event: _finite_number(rates[event], f"{uid}.rate.{event}")
            for event in EVENT_HAZARDS
        }
        if any(rate < 0 for rate in parsed_rates.values()):
            raise ContractError(f"{uid}: event rates must be nonnegative")
        state = m.get("state")
        if state not in ALLOWED_STATES:
            raise ContractError(f"{uid}: state must be one of {ALLOWED_STATES}")
        birth = _finite_number(m.get("birth_time_days"), f"{uid}.birth_time_days")
        if birth < 0:
            raise ContractError(f"{uid}: birth_time_days must be >= 0")
        return cls(
            object_uid=uid,
            object_class=_nonblank(m.get("object_class"), f"{uid}.object_class"),
            asset_key=_nonblank(m.get("asset_key"), f"{uid}.asset_key"),
            region_id=_nonblank(m.get("region_id"), f"{uid}.region_id"),
            geometry_version=_integer(m.get("geometry_version"), f"{uid}.geometry_version", minimum=1),
            birth_time_days=birth,
            state=state,
            pose=Pose.parse(m.get("pose"), f"{uid}.pose"),
            event_rates_per_day=parsed_rates,
        )


@dataclass(frozen=True)
class WorldState:
    schema_version: str
    world_id: str
    scene_family: str
    history_seed: int
    time_unit: str
    coordinate_frame: str
    width_m: float
    height_m: float
    time_days: float
    objects: tuple[WorldObject, ...]

    @classmethod
    def parse(cls, source: Any) -> "WorldState":
        m = _mapping(source, "world")
        if m.get("schema_version") != SCHEMA_VERSION:
            raise ContractError(f"schema_version must be {SCHEMA_VERSION}")
        if m.get("time_unit") != "days_since_world_origin":
            raise ContractError("time_unit must be days_since_world_origin")
        if m.get("coordinate_frame") != "world_enu":
            raise ContractError("coordinate_frame must be world_enu")
        width = _finite_number(m.get("width_m"), "width_m")
        height = _finite_number(m.get("height_m"), "height_m")
        time_days = _finite_number(m.get("time_days"), "time_days")
        if min(width, height) <= 0 or time_days < 0:
            raise ContractError("world dimensions must be > 0 and time_days >= 0")
        raw_objects = m.get("objects")
        if not isinstance(raw_objects, list):
            raise ContractError("objects must be a list")
        objects = tuple(sorted((WorldObject.parse(obj) for obj in raw_objects), key=lambda o: o.object_uid))
        ids = [obj.object_uid for obj in objects]
        if len(ids) != len(set(ids)):
            raise ContractError("object_uid values must be unique within the world")
        for obj in objects:
            if obj.birth_time_days > time_days:
                raise ContractError(f"{obj.object_uid}: birth time is later than snapshot time")
            if not (0 <= obj.pose.x_m <= width and 0 <= obj.pose.y_m <= height):
                raise ContractError(f"{obj.object_uid}: x/y pose lies outside the world bounds")
        return cls(
            schema_version=SCHEMA_VERSION,
            world_id=_nonblank(m.get("world_id"), "world_id"),
            scene_family=_nonblank(m.get("scene_family"), "scene_family"),
            history_seed=_integer(m.get("history_seed"), "history_seed"),
            time_unit="days_since_world_origin",
            coordinate_frame="world_enu",
            width_m=width,
            height_m=height,
            time_days=time_days,
            objects=objects,
        )

    def canonical_json(self) -> str:
        """Stable formatting and object ordering for exact-world comparison."""
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False)

    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def load_world(path: str | Path) -> WorldState:
    with Path(path).open("r", encoding="utf-8") as f:
        return WorldState.parse(json.load(f))
