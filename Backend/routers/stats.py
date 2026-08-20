"""
routers/stats.py
Person 2 — Backend Logic, Rules & LLM Integration

Endpoints: current headcount, peak times, heatmap data.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

from fastapi import APIRouter

sys.path.append(str(Path(__file__).resolve().parent.parent))
from database import get_connection  # noqa: E402
from services.stats_aggregator import get_peak_times  # noqa: E402

router = APIRouter()


@router.get("/current")
def current_headcount():
    """Latest known person count per zone, from the most recent raw_detections rows."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT zone_id, person_count, timestamp
            FROM raw_detections r
            WHERE timestamp = (
                SELECT MAX(timestamp) FROM raw_detections r2 WHERE r2.zone_id = r.zone_id
            )
            ORDER BY zone_id
            """
        ).fetchall()

        zones = [{"zone_id": r["zone_id"], "person_count": r["person_count"]} for r in rows]
        total = sum(z["person_count"] for z in zones)
        latest_ts = rows[0]["timestamp"] if rows else None

        return {"as_of": latest_ts, "total_count": total, "zones": zones}
    finally:
        conn.close()


@router.get("/summary")
def gym_summary():
    """Consolidated summary for dashboard startup or quick-refresh."""
    current = current_headcount()
    conn = get_connection()
    try:
        peaks = get_peak_times(conn, top_n=5)
        return {
            "status": "ok",
            "current": current,
            "peak_times": peaks,
        }
    finally:
        conn.close()


@router.get("/peak-times")
def peak_times(top_n: int = 5):
    """Busiest (day, hour) slots across all zones, from heatmap_data."""
    conn = get_connection()
    try:
        return {"peak_times": get_peak_times(conn, top_n=top_n)}
    finally:
        conn.close()


@router.get("/heatmap")
def heatmap_data():
    """Full heatmap: avg person count per zone / day_of_week / hour_of_day.
    Shaped for the dashboard's Chart.js heatmap directly."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT zone_id, day_of_week, hour_of_day, avg_person_count FROM heatmap_data"
        ).fetchall()
        return {
            "data": [
                {
                    "zone_id": r["zone_id"],
                    "day_of_week": r["day_of_week"],
                    "hour_of_day": r["hour_of_day"],
                    "avg_person_count": r["avg_person_count"],
                }
                for r in rows
            ]
        }
    finally:
        conn.close()


@router.get("/hourly")
def hourly_stats(hours: int = 24):
    """Recent hourly stats per zone — good for a time-series chart."""
    conn = get_connection()
    try:
        since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        rows = conn.execute(
            "SELECT * FROM hourly_stats WHERE hour_start >= ? ORDER BY hour_start",
            (since,),
        ).fetchall()
        return {
            "data": [
                {
                    "hour_start": r["hour_start"],
                    "zone_id": r["zone_id"],
                    "avg_person_count": r["avg_person_count"],
                    "max_person_count": r["max_person_count"],
                    "equipment_idle_minutes": r["equipment_idle_minutes"],
                }
                for r in rows
            ]
        }
    finally:
        conn.close()
