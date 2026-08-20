"""
ingest_cv_pipeline.py
Person 2 — Backend Logic, Rules & LLM Integration

Bridges Person 1's computer-vision pipeline output into our raw_detections
table, so stats_aggregator.py / rule_engine.py work on real detection data
instead of the mock seeder.

Person 1's pipeline produces, per logged data point (see run_pipeline.py):
    {
        "timestamp": <seconds into video>,
        "wall_clock": <ISO datetime string>,
        "total_count": <int>,
        "zone_counts": {zone_id: count, ...},
        "equipment_status": [
            {"id", "name", "type", "zone_id", "status",
             "idle_minutes", "continuous_busy_minutes"},
            ...
        ]
    }

Our raw_detections schema is one row per (timestamp, zone_id) for people,
plus one row per (timestamp, equipment) for equipment state. This module
adapts between the two shapes.

Two ways to feed this, matching Person 1's README:
  1. ingest_snapshot(snapshot)      -> live callback, wire directly into
                                        run_pipeline.py / PersonDetector's
                                        on_data_point hook for a running system.
  2. ingest_from_jsonl_log(path)    -> offline/batch: replays Person 1's
                                        person_log.jsonl (raw per-point
                                        detections) through ZoneTracker to
                                        reconstruct the same snapshots, then
                                        ingests them. This is what we use for
                                        testing/backfilling against a video
                                        that's already been processed.

Equipment status mapping (Person 1's richer states -> our simpler schema):
    in_use, heavily_used   -> "in_use"   (idle_seconds = 0)
    idle, possibly_broken  -> "idle"     (idle_seconds = idle_minutes * 60)
    unknown                -> NULL       (not enough data yet, skip)
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.append(str(Path(__file__).resolve().parent.parent))
from database import get_connection  # noqa: E402
from services.zone_tracker import ZoneTracker  # noqa: E402

DEFAULT_ZONES_CONFIG = Path(__file__).resolve().parent.parent / "data" / "zones_config.json"
DEFAULT_JSONL_LOG = Path(__file__).resolve().parent.parent / "data" / "person_log.jsonl"

_STATUS_MAP = {
    "in_use": "in_use",
    "heavily_used": "in_use",
    "idle": "idle",
    "possibly_broken": "idle",
    "unknown": None,
}


def _parse_wall_clock(wall_clock: str) -> str:
    """Person 1's wall_clock is ISO format; our schema wants 'YYYY-MM-DD HH:MM:SS'."""
    dt = datetime.fromisoformat(wall_clock)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _snapshot_to_rows(snapshot: dict) -> list[tuple]:
    """Convert one Person-1-style snapshot into raw_detections row tuples:
    (timestamp, zone_id, person_count, equipment_id, equipment_status, idle_seconds)"""
    ts = _parse_wall_clock(snapshot["wall_clock"])
    rows = []

    # One row per zone: people count
    for zone_id, count in snapshot["zone_counts"].items():
        rows.append((ts, zone_id, count, None, None, 0))

    # One row per equipment: status/idle info (person_count=0 to avoid
    # double-counting — the zone-level row above already counted people)
    for eq in snapshot["equipment_status"]:
        mapped_status = _STATUS_MAP.get(eq["status"])
        if mapped_status is None:
            continue  # "unknown" — not enough data yet, skip
        idle_seconds = int((eq["idle_minutes"] or 0) * 60) if mapped_status == "idle" else 0
        rows.append((ts, eq["zone_id"], 0, eq["id"], mapped_status, idle_seconds))

    return rows


def ingest_snapshot(snapshot: dict) -> int:
    """Live entry point — wire this into PersonDetector's on_data_point
    callback (or swap in for run_pipeline.py's print(json.dumps(snapshot)))
    for a running system. Returns number of rows written."""
    rows = _snapshot_to_rows(snapshot)
    if not rows:
        return 0

    conn = get_connection()
    try:
        conn.executemany(
            """INSERT INTO raw_detections
               (timestamp, zone_id, person_count, equipment_id, equipment_status, idle_seconds)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def ingest_from_jsonl_log(jsonl_path: Path = DEFAULT_JSONL_LOG,
                           zones_config_path: Path = DEFAULT_ZONES_CONFIG) -> dict:
    """Offline/batch entry point — replays Person 1's raw per-point
    detections (person_log.jsonl) through ZoneTracker to reconstruct the
    same zone_counts/equipment_status snapshots run_pipeline.py would have
    produced live, then ingests them into raw_detections."""
    tracker = ZoneTracker(str(zones_config_path))

    total_rows = 0
    total_points = 0

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            point = json.loads(line)

            centroids = [d["centroid"] for d in point["detections"]]
            tracker.update(person_centroids=centroids, timestamp=point["timestamp"])

            snapshot = {
                "timestamp": point["timestamp"],
                "wall_clock": point["wall_clock"],
                "total_count": point["count"],
                "zone_counts": tracker.get_zone_counts(),
                "equipment_status": tracker.get_equipment_status(current_timestamp=point["timestamp"]),
            }
            total_rows += ingest_snapshot(snapshot)
            total_points += 1

    return {"data_points_processed": total_points, "raw_detections_rows_written": total_rows}


if __name__ == "__main__":
    result = ingest_from_jsonl_log()
    print(json.dumps(result, indent=2))
