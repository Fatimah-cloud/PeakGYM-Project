"""
seed_mock_data.py
Person 2 — Backend Logic, Rules & LLM Integration

Fills raw_detections with fake-but-realistic data so we can build and
test stats_aggregator.py, rule_engine.py, etc. WITHOUT waiting on
Person 1's detection pipeline. Once Person 1 delivers real data, this
script just stops being needed (their pipeline writes to the same
raw_detections table).

Run from the backend/ folder:
    python data/seed_mock_data.py
"""

import sys
import random
from pathlib import Path
from datetime import datetime, timedelta

sys.path.append(str(Path(__file__).resolve().parent.parent))
from database import init_db, get_connection  # noqa: E402

ZONES = ["cardio_zone", "free_weights", "squat_rack_1", "bench_press_area", "stretching_area"]
EQUIPMENT = {
    "squat_rack_1": "squat_rack_1",
    "bench_press_area": "bench_press_1",
}


def seed(days_back: int = 3, interval_minutes: int = 5):
    init_db()
    conn = get_connection()
    now = datetime.now()
    start = now - timedelta(days=days_back)

    rows = []
    t = start
    while t <= now:
        hour = t.hour
        # crude "busyness" curve: quiet at night, peaks 6-9am and 5-9pm
        if 6 <= hour <= 9 or 17 <= hour <= 21:
            base_load = random.randint(8, 25)
        elif 10 <= hour <= 16:
            base_load = random.randint(3, 12)
        else:
            base_load = random.randint(0, 3)

        for zone in ZONES:
            count = max(0, base_load + random.randint(-3, 3))
            equipment_id = EQUIPMENT.get(zone)
            equipment_status = None
            idle_seconds = 0
            if equipment_id:
                equipment_status = "in_use" if count > 2 else "idle"
                idle_seconds = 0 if equipment_status == "in_use" else random.randint(0, 3600)

            rows.append((t.strftime("%Y-%m-%d %H:%M:%S"), zone, count,
                         equipment_id, equipment_status, idle_seconds))

        t += timedelta(minutes=interval_minutes)

    conn.executemany(
        """INSERT INTO raw_detections
           (timestamp, zone_id, person_count, equipment_id, equipment_status, idle_seconds)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    conn.close()
    print(f"Seeded {len(rows)} mock raw_detections rows "
          f"({days_back} days back, every {interval_minutes} min).")


if __name__ == "__main__":
    seed()
