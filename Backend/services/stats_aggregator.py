"""
stats_aggregator.py
Person 2 — Backend Logic, Rules & LLM Integration

Turns raw_detections (written every ~30s by Person 1's pipeline, or by
our mock seeder) into two things the rest of the app actually reads:

1. hourly_stats   -> rolling averages per zone per hour (for the peak-
                      time table and for rule_engine.py)
2. heatmap_data   -> avg person_count per (zone, day_of_week, hour_of_day),
                      exactly what the dashboard heatmap needs

Meant to be called on a schedule (scheduler.py will call
`run_hourly_aggregation()` every hour), but every function also works
fine called manually/on-demand — handy for testing.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
from database import get_connection  # noqa: E402


def _load_raw(conn, since: datetime | None = None) -> pd.DataFrame:
    """Load raw_detections into a DataFrame, optionally only rows after `since`."""
    query = "SELECT * FROM raw_detections"
    params: tuple = ()
    if since is not None:
        query += " WHERE timestamp >= ?"
        params = (since.strftime("%Y-%m-%d %H:%M:%S"),)

    df = pd.read_sql_query(query, conn, params=params)
    if df.empty:
        return df

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


# ---------------------------------------------------------------------
# 1. Hourly stats (avg / max person count per zone per hour)
# ---------------------------------------------------------------------
def compute_hourly_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Group raw readings into one row per (hour_start, zone_id)."""
    if df.empty:
        return pd.DataFrame(columns=[
            "hour_start", "zone_id", "avg_person_count",
            "max_person_count", "equipment_idle_minutes",
        ])

    df = df.copy()
    df["hour_start"] = df["timestamp"].dt.floor("h")

    grouped = (
        df.groupby(["hour_start", "zone_id"])
        .agg(
            avg_person_count=("person_count", "mean"),
            max_person_count=("person_count", "max"),
        )
        .reset_index()
    )

    # Idle minutes: idle_seconds in each raw_detections row is a CUMULATIVE
    # "how long has this piece of equipment been idle so far" counter (it
    # grows with every snapshot taken during the same idle streak — see
    # ingest_cv_pipeline.py). Summing that across every snapshot in the hour
    # re-counts the same elapsed time over and over (e.g. idle for 100s,
    # sampled every 10s, gives readings 10,20,...,100 — summing those is
    # 550s of "idle time" for 100s of real idle time). It was also grouped
    # by zone_id only, silently mixing multiple pieces of equipment in the
    # same zone into one running total.
    #
    # Fix: take the MAX cumulative idle_seconds per (hour, zone, equipment)
    # first — that's the true total idle duration that streak reached
    # during the hour — THEN sum those per-equipment maxes within the zone,
    # which correctly adds up idle time ACROSS different machines rather
    # than re-summing repeated samples of the same machine's single streak.
    idle_per_equipment = (
        df[df["equipment_status"] == "idle"]
        .groupby(["hour_start", "zone_id", "equipment_id"])["idle_seconds"]
        .max()
        .reset_index()
    )
    idle = (
        idle_per_equipment
        .groupby(["hour_start", "zone_id"])["idle_seconds"]
        .sum()
        .div(60)
        .rename("equipment_idle_minutes")
        .reset_index()
    )

    grouped = grouped.merge(idle, on=["hour_start", "zone_id"], how="left")
    grouped["equipment_idle_minutes"] = grouped["equipment_idle_minutes"].fillna(0).round(1)
    grouped["avg_person_count"] = grouped["avg_person_count"].round(2)

    return grouped


def save_hourly_stats(conn, hourly_df: pd.DataFrame) -> int:
    """Upsert hourly_df into hourly_stats. Returns number of rows written."""
    if hourly_df.empty:
        return 0

    rows = [
        (
            row.hour_start.strftime("%Y-%m-%d %H:%M:%S"),
            row.zone_id,
            float(row.avg_person_count),
            int(row.max_person_count),
            float(row.equipment_idle_minutes),
        )
        for row in hourly_df.itertuples(index=False)
    ]

    conn.executemany(
        """
        INSERT INTO hourly_stats
            (hour_start, zone_id, avg_person_count, max_person_count, equipment_idle_minutes)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(hour_start, zone_id) DO UPDATE SET
            avg_person_count = excluded.avg_person_count,
            max_person_count = excluded.max_person_count,
            equipment_idle_minutes = excluded.equipment_idle_minutes
        """,
        rows,
    )
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------
# 2. Heatmap data (avg person count per zone / day_of_week / hour_of_day)
# ---------------------------------------------------------------------
def compute_heatmap(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["zone_id", "day_of_week", "hour_of_day", "avg_person_count"])

    df = df.copy()
    df["day_of_week"] = df["timestamp"].dt.dayofweek  # 0=Monday
    df["hour_of_day"] = df["timestamp"].dt.hour

    grouped = (
        df.groupby(["zone_id", "day_of_week", "hour_of_day"])["person_count"]
        .mean()
        .round(2)
        .rename("avg_person_count")
        .reset_index()
    )
    return grouped


def save_heatmap(conn, heatmap_df: pd.DataFrame) -> int:
    if heatmap_df.empty:
        return 0

    rows = [
        (row.zone_id, int(row.day_of_week), int(row.hour_of_day), float(row.avg_person_count))
        for row in heatmap_df.itertuples(index=False)
    ]

    conn.executemany(
        """
        INSERT INTO heatmap_data (zone_id, day_of_week, hour_of_day, avg_person_count)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(zone_id, day_of_week, hour_of_day) DO UPDATE SET
            avg_person_count = excluded.avg_person_count
        """,
        rows,
    )
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------
# 3. Peak-time table — convenience read used directly by /stats/peak-times
# ---------------------------------------------------------------------
def get_peak_times(conn, top_n: int = 5) -> list[dict]:
    """Busiest (day_of_week, hour_of_day) slots across all zones, combined."""
    df = pd.read_sql_query("SELECT * FROM heatmap_data", conn)
    if df.empty:
        return []

    combined = (
        df.groupby(["day_of_week", "hour_of_day"])["avg_person_count"]
        .sum()
        .reset_index()
        .sort_values("avg_person_count", ascending=False)
        .head(top_n)
    )

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return [
        {
            "day": day_names[int(row.day_of_week)],
            "hour": int(row.hour_of_day),
            "avg_total_person_count": round(float(row.avg_person_count), 1),
        }
        for row in combined.itertuples(index=False)
    ]


# ---------------------------------------------------------------------
# Entry point for scheduler.py
# ---------------------------------------------------------------------
def run_hourly_aggregation(lookback_hours: int = 48) -> dict:
    """Recompute hourly_stats and heatmap_data from recent raw_detections.
    Re-aggregating a rolling window (not just the last hour) makes this
    safe to re-run if a job was missed or raw data arrived late."""
    conn = get_connection()
    try:
        since = datetime.now() - timedelta(hours=lookback_hours)
        df = _load_raw(conn, since=since)

        hourly_df = compute_hourly_stats(df)
        heatmap_df = compute_heatmap(df)

        hourly_written = save_hourly_stats(conn, hourly_df)
        heatmap_written = save_heatmap(conn, heatmap_df)

        return {
            "raw_rows_processed": len(df),
            "hourly_stats_rows_written": hourly_written,
            "heatmap_rows_written": heatmap_written,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    result = run_hourly_aggregation()
    print(result)
