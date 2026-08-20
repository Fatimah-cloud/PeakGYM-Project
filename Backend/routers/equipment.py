"""
routers/equipment.py
Person 2 — Backend Logic, Rules & LLM Integration

Endpoint: equipment status list.
"""

import sys
from pathlib import Path

from fastapi import APIRouter

sys.path.append(str(Path(__file__).resolve().parent.parent))
from database import get_connection  # noqa: E402

router = APIRouter()


@router.get("/status")
def equipment_status():
    """Latest known status per piece of equipment, from the most recent
    raw_detections rows that mention that equipment_id."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT equipment_id, zone_id, equipment_status, idle_seconds, timestamp
            FROM raw_detections r
            WHERE equipment_id IS NOT NULL
            AND timestamp = (
                SELECT MAX(timestamp) FROM raw_detections r2
                WHERE r2.equipment_id = r.equipment_id
            )
            ORDER BY equipment_id
            """
        ).fetchall()

        return {
            "equipment": [
                {
                    "equipment_id": r["equipment_id"],
                    "zone_id": r["zone_id"],
                    "status": r["equipment_status"],
                    "idle_minutes": round((r["idle_seconds"] or 0) / 60, 1),
                    "as_of": r["timestamp"],
                }
                for r in rows
            ]
        }
    finally:
        conn.close()
