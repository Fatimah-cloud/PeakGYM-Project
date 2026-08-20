"""
rule_engine.py
Person 2 — Backend Logic, Rules & LLM Integration

Reads from hourly_stats / heatmap_data (built by stats_aggregator.py)
and evaluates 4 threshold-based rules, defined in data/rules_config.json:

    1. zone_imbalance      -> one zone much busier than the gym average
    2. idle_equipment      -> equipment idle too long during open hours
    3. underused_zone      -> a zone is consistently near-empty
    4. peak_time_mismatch  -> real busy hours differ from expected/staffed hours

Any triggered rule is written to rule_triggers, which
llm_recommender.py later reads to build its Claude API prompt.

Meant to run on a schedule (scheduler.py calls `run_all_rules()`
hourly), but each rule function also works standalone for testing.
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
from database import get_connection  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "rules_config.json"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_trigger(conn, rule_name: str, zone_id: str | None,
                   equipment_id: str | None, details: dict) -> None:
    # Skip if an unresolved trigger for this exact (rule, zone, equipment)
    # already exists — without this, re-running the checks more often than
    # the original once-an-hour design (e.g. continuously during a live
    # demo) piles up duplicate unresolved rows for the same ongoing issue,
    # which then all get bundled into one recommendation and produce the
    # same sentence repeated several times over.
    existing = conn.execute(
        """SELECT 1 FROM rule_triggers
           WHERE rule_name = ? AND resolved = 0
           AND zone_id IS ? AND equipment_id IS ?
           LIMIT 1""",
        (rule_name, zone_id, equipment_id),
    ).fetchone()
    if existing:
        return

    conn.execute(
        """INSERT INTO rule_triggers (rule_name, zone_id, equipment_id, details_json)
           VALUES (?, ?, ?, ?)""",
        (rule_name, zone_id, equipment_id, json.dumps(details)),
    )


# ---------------------------------------------------------------------
# Rule 1: zone_imbalance
# ---------------------------------------------------------------------
def check_zone_imbalance(conn, config: dict, lookback_hours: int = 3) -> list[dict]:
    """Flag zones whose recent avg_person_count is far above the
    gym-wide average for the same hours."""
    cfg = config["zone_imbalance"]
    since = (datetime.now() - timedelta(hours=lookback_hours)).strftime("%Y-%m-%d %H:%M:%S")

    df = pd.read_sql_query(
        "SELECT * FROM hourly_stats WHERE hour_start >= ?", conn, params=(since,)
    )
    if df.empty:
        return []

    triggers = []
    gym_avg = df["avg_person_count"].mean()
    if gym_avg <= 0:
        return []

    per_zone = df.groupby("zone_id")["avg_person_count"].mean()
    for zone_id, zone_avg in per_zone.items():
        if zone_avg < cfg["min_person_count"]:
            continue
        ratio = zone_avg / gym_avg
        if ratio >= cfg["ratio_threshold"]:
            details = {
                "zone_avg_person_count": round(float(zone_avg), 2),
                "gym_avg_person_count": round(float(gym_avg), 2),
                "ratio": round(float(ratio), 2),
                "lookback_hours": lookback_hours,
            }
            _save_trigger(conn, "zone_imbalance", zone_id, None, details)
            triggers.append({"zone_id": zone_id, **details})

    return triggers


# ---------------------------------------------------------------------
# Rule 2: idle_equipment
# ---------------------------------------------------------------------
def check_idle_equipment(conn, config: dict, lookback_hours: int = 3) -> list[dict]:
    """Flag zones/equipment idle longer than the configured threshold
    within the lookback window."""
    cfg = config["idle_equipment"]
    since = (datetime.now() - timedelta(hours=lookback_hours)).strftime("%Y-%m-%d %H:%M:%S")

    df = pd.read_sql_query(
        "SELECT * FROM hourly_stats WHERE hour_start >= ?", conn, params=(since,)
    )
    if df.empty:
        return []

    triggers = []
    idle_totals = df.groupby("zone_id")["equipment_idle_minutes"].sum()
    for zone_id, idle_minutes in idle_totals.items():
        if idle_minutes >= cfg["idle_minutes_threshold"]:
            details = {
                "idle_minutes": round(float(idle_minutes), 1),
                "threshold_minutes": cfg["idle_minutes_threshold"],
                "lookback_hours": lookback_hours,
            }
            _save_trigger(conn, "idle_equipment", zone_id, zone_id, details)
            triggers.append({"zone_id": zone_id, **details})

    return triggers


# ---------------------------------------------------------------------
# Rule 3: underused_zone
# ---------------------------------------------------------------------
def check_underused_zone(conn, config: dict) -> list[dict]:
    """Flag zones whose max_person_count stayed low for the whole
    lookback window (e.g. an area nobody uses)."""
    cfg = config["underused_zone"]
    since = (datetime.now() - timedelta(hours=cfg["lookback_hours"])).strftime("%Y-%m-%d %H:%M:%S")

    df = pd.read_sql_query(
        "SELECT * FROM hourly_stats WHERE hour_start >= ?", conn, params=(since,)
    )
    if df.empty:
        return []

    triggers = []
    per_zone_max = df.groupby("zone_id")["max_person_count"].max()
    for zone_id, zone_max in per_zone_max.items():
        if zone_max <= cfg["max_person_count_threshold"]:
            details = {
                "max_person_count": int(zone_max),
                "threshold": cfg["max_person_count_threshold"],
                "lookback_hours": cfg["lookback_hours"],
            }
            _save_trigger(conn, "underused_zone", zone_id, None, details)
            triggers.append({"zone_id": zone_id, **details})

    return triggers


# ---------------------------------------------------------------------
# Rule 4: peak_time_mismatch
# ---------------------------------------------------------------------
def check_peak_time_mismatch(conn, config: dict) -> list[dict]:
    """Compare actual busiest hours (from heatmap_data) against the
    gym's expected/staffed peak hours. Flags real peaks that fall
    outside expected hours by more than the deviation threshold."""
    cfg = config["peak_time_mismatch"]

    df = pd.read_sql_query("SELECT * FROM heatmap_data", conn)
    if df.empty:
        return []

    by_hour = df.groupby("hour_of_day")["avg_person_count"].mean()
    if by_hour.empty:
        return []

    overall_avg = by_hour.mean()
    expected_hours = set(cfg["expected_peak_hours"])

    triggers = []
    for hour, avg_count in by_hour.items():
        if hour in expected_hours:
            continue
        if overall_avg <= 0:
            continue
        deviation = avg_count / overall_avg
        if deviation >= cfg["deviation_threshold"]:
            details = {
                "hour_of_day": int(hour),
                "avg_person_count": round(float(avg_count), 2),
                "overall_avg_person_count": round(float(overall_avg), 2),
                "deviation_ratio": round(float(deviation), 2),
            }
            _save_trigger(conn, "peak_time_mismatch", None, None, details)
            triggers.append(details)

    return triggers


# ---------------------------------------------------------------------
# Entry point for scheduler.py
# ---------------------------------------------------------------------
def run_all_rules() -> dict:
    conn = get_connection()
    try:
        config = load_config()
        results = {
            "zone_imbalance": check_zone_imbalance(conn, config),
            "idle_equipment": check_idle_equipment(conn, config),
            "underused_zone": check_underused_zone(conn, config),
            "peak_time_mismatch": check_peak_time_mismatch(conn, config),
        }
        conn.commit()
        return {name: len(triggers) for name, triggers in results.items()} | {"_raw": results}
    finally:
        conn.close()


if __name__ == "__main__":
    result = run_all_rules()
    for name, count in result.items():
        if name == "_raw":
            continue
        print(f"{name}: {count} trigger(s)")
    print()
    print("Details:")
    print(json.dumps(result["_raw"], indent=2, default=str))
