-- Smart Gym Monitoring System - Database Schema
-- Person 2: Backend Logic, Rules & LLM Integration

-- ============================================================
-- RAW DATA
-- Every ~30s, Person 1's detection pipeline writes a snapshot
-- here. Until that pipeline is ready, we insert mock rows so
-- the rest of the backend can be built and tested independently.
-- ============================================================
CREATE TABLE IF NOT EXISTS raw_detections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       DATETIME NOT NULL DEFAULT (datetime('now')),
    zone_id         TEXT NOT NULL,          -- e.g. "cardio_zone", "squat_rack_1"
    person_count    INTEGER NOT NULL DEFAULT 0,
    equipment_id    TEXT,                   -- NULL if this row is just a person-count reading
    equipment_status TEXT,                  -- 'in_use' | 'idle' | 'unknown'
    idle_seconds    INTEGER DEFAULT 0        -- how long equipment_id has been idle, if applicable
);

CREATE INDEX IF NOT EXISTS idx_raw_timestamp ON raw_detections(timestamp);
CREATE INDEX IF NOT EXISTS idx_raw_zone ON raw_detections(zone_id);

-- ============================================================
-- AGGREGATED STATS
-- Built by stats_aggregator.py on a schedule (hourly job via
-- scheduler.py). This is what the dashboard and rule_engine
-- actually read from — much cheaper than scanning raw_detections
-- every time.
-- ============================================================
CREATE TABLE IF NOT EXISTS hourly_stats (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    hour_start      DATETIME NOT NULL,      -- start of the hour this row summarizes
    zone_id         TEXT NOT NULL,
    avg_person_count REAL NOT NULL DEFAULT 0,
    max_person_count INTEGER NOT NULL DEFAULT 0,
    equipment_idle_minutes INTEGER DEFAULT 0,
    UNIQUE(hour_start, zone_id)
);

CREATE INDEX IF NOT EXISTS idx_hourly_start ON hourly_stats(hour_start);

-- Heatmap data: zone popularity per hour-of-day / day-of-week,
-- used directly by /stats/heatmap endpoint
CREATE TABLE IF NOT EXISTS heatmap_data (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    zone_id         TEXT NOT NULL,
    day_of_week     INTEGER NOT NULL,       -- 0=Monday ... 6=Sunday
    hour_of_day     INTEGER NOT NULL,       -- 0-23
    avg_person_count REAL NOT NULL DEFAULT 0,
    UNIQUE(zone_id, day_of_week, hour_of_day)
);

-- ============================================================
-- RULE ENGINE OUTPUT
-- rule_engine.py evaluates thresholds from rules_config.json
-- and logs any triggered rule here. llm_recommender.py reads
-- recent unresolved triggers to build its Claude API prompt.
-- ============================================================
CREATE TABLE IF NOT EXISTS rule_triggers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       DATETIME NOT NULL DEFAULT (datetime('now')),
    rule_name       TEXT NOT NULL,          -- 'zone_imbalance' | 'idle_equipment' | 'underused_zone' | 'peak_time_mismatch'
    zone_id         TEXT,
    equipment_id    TEXT,
    details_json    TEXT,                   -- free-form JSON with rule-specific context
    resolved        INTEGER NOT NULL DEFAULT 0  -- 0/1, so we don't re-report the same issue forever
);

-- ============================================================
-- LLM RECOMMENDATIONS
-- Stores each recommendation returned by Claude so the
-- /recommendations endpoint can just read the latest row.
-- ============================================================
CREATE TABLE IF NOT EXISTS llm_recommendations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       DATETIME NOT NULL DEFAULT (datetime('now')),
    recommendation_text TEXT NOT NULL,
    based_on_triggers   TEXT,               -- JSON list of rule_triggers.id used as input
    report_type     TEXT NOT NULL DEFAULT 'live'  -- 'live' | 'monthly'
);
