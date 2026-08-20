"""
zone_tracker.py
----------------
Person 1 — Computer Vision (Detection & Tracking)

Takes the raw person (and equipment) detections produced every frame and maps
them onto the zones/equipment ROIs defined in data/zones_config.json.

Responsibilities:
  - Per-zone people count (feeds the heatmap in stats_aggregator.py)
  - Per-equipment "in use" / "idle" / "possibly broken" status, based on how
    long it's been since a person was last detected overlapping that
    equipment's ROI (feeds rule_engine.py's idle-equipment rule)

This module is pure geometry + bookkeeping (no LLM, matches the spec:
"Crowd and space analysis (plain code logic, no LLM)").

Usage:
    tracker = ZoneTracker("backend/data/zones_config.json")

    # called every frame/data point, with the person centroids from
    # person_detector.py and (optionally) equipment-in-use info from
    # equipment_detector.py
    tracker.update(person_centroids=[[512, 300], [900, 420]], timestamp=123.4)

    zone_counts = tracker.get_zone_counts()
    equipment_status = tracker.get_equipment_status(current_timestamp=123.4)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional


def _point_in_bbox(point: list[float], bbox: list[float]) -> bool:
    x, y = point
    x1, y1, x2, y2 = bbox
    return x1 <= x <= x2 and y1 <= y <= y2


@dataclass
class EquipmentState:
    id: str
    name: str
    type: str
    zone_id: str
    bbox: list
    idle_threshold_minutes: float
    busy_threshold_minutes: float
    last_used_timestamp: Optional[float] = None   # seconds, video/stream time
    currently_occupied: bool = False
    busy_streak_start: Optional[float] = None      # when continuous use began


class ZoneTracker:
    def __init__(self, zones_config_path: str, occupancy_grace_seconds: float = 3.0):
        """
        occupancy_grace_seconds: if update() is being called on every frame
            (recommended — see run_pipeline.py's on_frame usage), a person
            can flicker in and out of detection for a single frame due to
            motion blur, brief occlusion, or a borderline confidence score.
            Without a grace period, that flicker would reset the "currently
            occupied" streak every time, making continuous_busy_minutes
            useless and making idle detection falsely trigger. This grace
            period means equipment is only considered "no longer occupied"
            after nobody's been detected on it for this many seconds, not
            after a single missed frame.
        """
        with open(zones_config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        self.zones = {z["id"]: z for z in config["zones"]}
        self.equipment: dict[str, EquipmentState] = {
            e["id"]: EquipmentState(
                id=e["id"], name=e["name"], type=e["type"], zone_id=e["zone_id"],
                bbox=e["bbox"],
                idle_threshold_minutes=e.get("idle_threshold_minutes", 5),
                busy_threshold_minutes=e.get("busy_threshold_minutes", 45),
            )
            for e in config["equipment"]
        }

        self._zone_counts: dict[str, int] = {zid: 0 for zid in self.zones}
        self._last_timestamp: Optional[float] = None
        self._monitoring_start_timestamp: Optional[float] = None
        self.occupancy_grace_seconds = occupancy_grace_seconds

    # ------------------------------------------------------------------ #
    # Zone assignment
    # ------------------------------------------------------------------ #
    def _zone_for_point(self, point: list[float]) -> Optional[str]:
        for zid, zone in self.zones.items():
            if _point_in_bbox(point, zone["bbox"]):
                return zid
        return None

    def _equipment_for_point(self, point: list[float]) -> list[str]:
        """A person can be near more than one piece of equipment (e.g. a
        walkway between two machines); return every match, caller can decide
        how to weight it. In practice ROIs should be drawn tight enough that
        this is usually 0 or 1 match."""
        return [eid for eid, eq in self.equipment.items()
                if _point_in_bbox(point, eq.bbox)]

    # ------------------------------------------------------------------ #
    # Main update step — call this once per logged data point
    # ------------------------------------------------------------------ #
    def update(self, person_centroids: list[list[float]], timestamp: float) -> None:
        """
        person_centroids: list of [x, y] centroids from PersonDetector for
                           this data point (same coordinate space as the
                           bboxes in zones_config.json).
        timestamp: seconds into the video/stream, matches PersonDetector's
                   DataPoint.timestamp.
        """
        self._last_timestamp = timestamp
        if self._monitoring_start_timestamp is None:
            self._monitoring_start_timestamp = timestamp

        # Reset & recompute zone counts for this snapshot
        zone_counts = {zid: 0 for zid in self.zones}
        occupied_equipment_ids: set[str] = set()

        for point in person_centroids:
            zid = self._zone_for_point(point)
            if zid:
                zone_counts[zid] += 1
            for eid in self._equipment_for_point(point):
                occupied_equipment_ids.add(eid)

        self._zone_counts = zone_counts

        # Update equipment occupancy / idle bookkeeping
        for eid, eq in self.equipment.items():
            if eid in occupied_equipment_ids:
                # Was this a fresh session, or a continuation within the
                # grace window of a previous one (i.e. flicker, not a real
                # gap)? Only start a new busy streak if there was a real gap.
                if not eq.currently_occupied:
                    gap = (timestamp - eq.last_used_timestamp
                            if eq.last_used_timestamp is not None else None)
                    if gap is None or gap > self.occupancy_grace_seconds:
                        eq.busy_streak_start = timestamp
                    # else: within grace window — treat as continuation,
                    # keep the existing busy_streak_start
                eq.last_used_timestamp = timestamp
                eq.currently_occupied = True
            else:
                # Not detected THIS frame — but don't immediately mark it
                # free; only do so once the grace period has actually
                # elapsed since it was last seen occupied.
                if eq.currently_occupied and eq.last_used_timestamp is not None:
                    if (timestamp - eq.last_used_timestamp) > self.occupancy_grace_seconds:
                        eq.currently_occupied = False
                        eq.busy_streak_start = None
                    # else: still within grace window, leave state as-is

    # ------------------------------------------------------------------ #
    # Read-outs for stats_aggregator.py / rule_engine.py
    # ------------------------------------------------------------------ #
    def get_zone_counts(self) -> dict:
        """{zone_id: current_person_count} — the raw input to the heatmap."""
        return dict(self._zone_counts)

    def get_equipment_status(self, current_timestamp: Optional[float] = None) -> list[dict]:
        """
        Returns one entry per piece of equipment with a status label:
          - "in_use"           : someone is on/at it right now
          - "idle"              : free, last used recently (normal) — OR
                                   never used at all since monitoring began,
                                   but not yet past idle_threshold_minutes
          - "possibly_broken"   : free for longer than idle_threshold_minutes
                                   -> this is the signal rule_engine.py turns
                                   into a "check this machine" recommendation.
                                   This INCLUDES equipment that has never
                                   been used at all since monitoring started
                                   — "nobody has ever touched this machine"
                                   is exactly the kind of thing this system
                                   exists to catch, not a case to hide.
          - "heavily_used"      : in continuous use beyond busy_threshold
                                   -> feeds the "recurring queue" rule
        """
        ts = current_timestamp if current_timestamp is not None else self._last_timestamp
        out = []
        for eq in self.equipment.values():
            idle_minutes = None
            busy_minutes = None
            status = "idle"

            if eq.currently_occupied:
                status = "in_use"
                if eq.busy_streak_start is not None and ts is not None:
                    busy_minutes = (ts - eq.busy_streak_start) / 60.0
                    if busy_minutes >= eq.busy_threshold_minutes:
                        status = "heavily_used"
            else:
                # last_used_timestamp is None for equipment that has NEVER
                # been detected as occupied — fall back to counting idle
                # time from when monitoring started, so "never used" still
                # surfaces as idle/possibly_broken instead of disappearing.
                reference_ts = eq.last_used_timestamp
                if reference_ts is None:
                    reference_ts = self._monitoring_start_timestamp

                if reference_ts is not None and ts is not None:
                    idle_minutes = (ts - reference_ts) / 60.0
                    if idle_minutes >= eq.idle_threshold_minutes:
                        status = "possibly_broken"

            out.append({
                "id": eq.id,
                "name": eq.name,
                "type": eq.type,
                "zone_id": eq.zone_id,
                "status": status,
                "idle_minutes": round(idle_minutes, 1) if idle_minutes is not None else None,
                "continuous_busy_minutes": round(busy_minutes, 1) if busy_minutes is not None else None,
            })
        return out

    def get_zone_metadata(self) -> dict:
        """Zone names + bboxes, for the dashboard to draw the heatmap overlay."""
        return {zid: {"name": z["name"], "bbox": z["bbox"]} for zid, z in self.zones.items()}


if __name__ == "__main__":
    # Minimal smoke test with fake centroids
    tracker = ZoneTracker("../data/zones_config.json")
    tracker.update(person_centroids=[[500, 100], [1000, 400], [1000, 400]], timestamp=0)
    print("Zone counts @0s:", tracker.get_zone_counts())
    tracker.update(person_centroids=[[500, 100]], timestamp=400)  # ~6.7 min later
    print("Zone counts @400s:", tracker.get_zone_counts())
    print("Equipment status @400s:")
    for e in tracker.get_equipment_status(current_timestamp=400):
        print(" ", e)
