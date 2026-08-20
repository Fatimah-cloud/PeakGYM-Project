"""
seed_gym_history.py
--------------------
Generates ~2 months of realistic historical data for this gym's real
zone/equipment layout (confirmed across multiple real camera-angle stills,
not the generic equipment-guide poster), so the dashboard has rich history
to show immediately instead of waiting for real usage to accumulate.

IMPORTANT: this deletes the existing stats_store.db first (new database,
not related to the previous test one). Back it up first if you want to
keep anything from it.

This does NOT touch zones_config.json's bbox coordinates or run any real
CV detection — it writes directly into raw_detections with synthetic-but-
realistic numbers, then calls your team's REAL aggregation functions
(stats_aggregator.compute_hourly_stats / compute_heatmap) so hourly_stats
and heatmap_data end up exactly as they would if this had come from real
usage. Nothing here duplicates or reimplements their logic.

Usage:
    cd backend
    python seed_gym_history.py
    # or: python seed_gym_history.py --days 60 --keep-existing
"""

import argparse
import math
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "stats_store.db"

# ---------------------------------------------------------------------
# This gym's real layout, confirmed across multiple real camera stills
# (not the generic equipment-guide poster — only what's actually visible
# and repeated across your footage). Keep these IDs in sync with
# data/zones_config.json.
# ---------------------------------------------------------------------

ZONES = [
    {"id": "zone_squat_bench", "name": "Squat Rack & Bench Area", "base_weight": 0.32},
    {"id": "zone_freeweights_aisle", "name": "Free Weights Aisle", "base_weight": 0.20},
    {"id": "zone_cable_stations", "name": "Cable / Functional Trainer Zone", "base_weight": 0.28},
    {"id": "zone_machine_row", "name": "Machine Row", "base_weight": 0.20},
]

EQUIPMENT = [
    {"id": "squat_rack_1", "zone": "zone_squat_bench", "popularity": 0.90},
    {"id": "squat_rack_2", "zone": "zone_squat_bench", "popularity": 0.80},
    {"id": "adjustable_bench_1", "zone": "zone_squat_bench", "popularity": 0.65},
    {"id": "adjustable_bench_2", "zone": "zone_squat_bench", "popularity": 0.55},
    {"id": "dumbbell_rack_1", "zone": "zone_freeweights_aisle", "popularity": 0.85},
    {"id": "cable_station_1", "zone": "zone_cable_stations", "popularity": 0.70},
    {"id": "cable_station_2", "zone": "zone_cable_stations", "popularity": 0.65},
    {"id": "cable_station_3", "zone": "zone_cable_stations", "popularity": 0.50},
    {"id": "leg_press_sled_1", "zone": "zone_machine_row", "popularity": 0.60},
    {"id": "leg_press_sled_2", "zone": "zone_machine_row", "popularity": 0.50},
    {"id": "chest_press_machine_1", "zone": "zone_machine_row", "popularity": 0.55},
]

OPEN_HOUR = 6    # 6 AM
CLOSE_HOUR = 23  # 11 PM
GYM_ROUGH_PEAK_CAPACITY = 55  # rough total headcount across all zones at absolute peak


def hourly_multiplier(hour: int, is_weekend: bool) -> float:
    """0..~1 curve: weekday evening peak (~7-8pm), weekend midday peak (~noon),
    quiet mid-morning/late-night otherwise. Matches a fairly standard gym."""
    peak_hour = 12 if is_weekend else 19
    spread = 4 if is_weekend else 3
    base_floor = 0.15 if is_weekend else 0.08
    bell = math.exp(-((hour - peak_hour) ** 2) / (2 * spread ** 2))
    scale = 0.75 if is_weekend else 1.0
    return base_floor + bell * scale


def simulate_day(conn, day_date: datetime) -> int:
    is_weekend = day_date.weekday() >= 5

    # ~5% of days: one piece of equipment goes idle/flagged for a few hours
    # (gives rule_engine's idle_equipment rule and the monthly report
    # something real to talk about, instead of a perfectly clean dataset).
    broken_id, broken_start, broken_hours = None, None, 0
    if random.random() < 0.05:
        broken_id = random.choice(EQUIPMENT)["id"]
        broken_start = random.randint(OPEN_HOUR, CLOSE_HOUR - 3)
        broken_hours = random.randint(2, 4)

    rows = []
    for hour in range(OPEN_HOUR, CLOSE_HOUR):
        mult = hourly_multiplier(hour, is_weekend)
        for minute in (0, 30):  # one data point every 30 min
            ts = day_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            total_now = max(0, round(GYM_ROUGH_PEAK_CAPACITY * mult * random.uniform(0.75, 1.15)))

            weights = [z["base_weight"] * random.uniform(0.8, 1.2) for z in ZONES]
            wsum = sum(weights)
            remaining = total_now
            for i, z in enumerate(ZONES):
                if i == len(ZONES) - 1:
                    count = remaining
                else:
                    count = min(remaining, round(total_now * weights[i] / wsum))
                    remaining -= count
                rows.append((ts.strftime("%Y-%m-%d %H:%M:%S"), z["id"], count, None, None, 0))

            for eq in EQUIPMENT:
                is_broken_now = (
                    broken_id == eq["id"]
                    and broken_start is not None
                    and broken_start <= hour < broken_start + broken_hours
                )
                if is_broken_now:
                    status, idle_seconds = "idle", random.randint(3600, 3600 * broken_hours)
                elif random.random() < eq["popularity"] * mult:
                    status, idle_seconds = "in_use", 0
                else:
                    status, idle_seconds = "idle", random.randint(60, 1200)
                rows.append((ts.strftime("%Y-%m-%d %H:%M:%S"), eq["zone"], 0, eq["id"], status, idle_seconds))

    conn.executemany(
        """INSERT INTO raw_detections
           (timestamp, zone_id, person_count, equipment_id, equipment_status, idle_seconds)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description="Seed ~2 months of realistic gym history")
    parser.add_argument("--days", type=int, default=60, help="How many days of history to generate")
    parser.add_argument("--keep-existing", action="store_true",
                         help="Don't delete the existing database first")
    args = parser.parse_args()

    if not args.keep_existing and DB_PATH.exists():
        DB_PATH.unlink()
        print(f"Deleted existing database: {DB_PATH}")

    sys.path.insert(0, str(BASE_DIR))
    from database import init_db, get_connection  # noqa: E402

    init_db()
    print("Fresh schema applied via your existing database.init_db().")

    conn = get_connection()
    end_date = datetime.now().replace(minute=0, second=0, microsecond=0)
    start_date = end_date - timedelta(days=args.days)

    total_rows = 0
    day = start_date
    while day < end_date:
        total_rows += simulate_day(conn, day)
        day += timedelta(days=1)
    conn.close()
    print(f"Inserted {total_rows} raw_detections rows across {args.days} days.")

    # Reuse the REAL aggregation code so hourly_stats/heatmap_data are
    # exactly what the live system would have computed from this data.
    from services.stats_aggregator import (  # noqa: E402
        _load_raw, compute_hourly_stats, compute_heatmap,
        save_hourly_stats, save_heatmap,
    )

    conn = get_connection()
    df = _load_raw(conn, since=start_date)
    hourly_df = compute_hourly_stats(df)
    heatmap_df = compute_heatmap(df)
    h_written = save_hourly_stats(conn, hourly_df)
    hm_written = save_heatmap(conn, heatmap_df)
    conn.close()

    print(f"Aggregated via real stats_aggregator.py: "
          f"{h_written} hourly_stats rows, {hm_written} heatmap_data rows.")
    print("\nDone. Start the backend as usual:")
    print("    uvicorn main:app --reload --port 8000")


if __name__ == "__main__":
    main()
