"""
llm_recommender.py
Person 2 — Backend Logic, Rules & LLM Integration

Reads unresolved rows from rule_triggers (written by rule_engine.py),
builds a compact JSON payload + prompt, and calls the Claude API to
turn raw threshold breaches into a short, actionable recommendation
for gym staff.

Needs an API key: set ANTHROPIC_API_KEY as an environment variable
(don't hardcode it). Easiest way locally: create a `.env` file next
to main.py with:
    ANTHROPIC_API_KEY=sk-ant-...
and load it with python-dotenv (already in requirements.txt).

Entry point for scheduler.py / routers/recommendations.py:
    generate_recommendation() -> dict
"""

import sys
import json
import os
from datetime import datetime
from pathlib import Path
try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

from dotenv import load_dotenv

sys.path.append(str(Path(__file__).resolve().parent.parent))
from database import get_connection  # noqa: E402

load_dotenv()

# gemini-2.5-flash: free-tier friendly, fast, good enough for turning
# structured rule-trigger data into a short staff-facing recommendation.
MODEL = "gemini-3.6-flash"

SYSTEM_PROMPT = """You are an operations assistant for a gym's staff dashboard.
You receive structured JSON describing rule violations detected by an
automated monitoring system (crowding imbalances, idle equipment,
underused zones, and peak-time mismatches).

Write a short, practical recommendation for gym staff based on this data.

Rules:
- Be specific: reference the actual zone names and numbers given.
- Prioritize the most actionable/urgent issue first if there are several.
- Keep it to 3-5 sentences, plain language, no jargon.
- Do not invent data that isn't in the payload.
- Respond with ONLY a JSON object, no markdown fences, no preamble, matching:
  {"recommendation": "<the recommendation text>", "priority": "low"|"medium"|"high"}
"""


def _load_unresolved_triggers(conn, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        """SELECT id, timestamp, rule_name, zone_id, equipment_id, details_json
           FROM rule_triggers
           WHERE resolved = 0
           ORDER BY timestamp DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()

    triggers = []
    for r in rows:
        triggers.append({
            "id": r["id"],
            "timestamp": r["timestamp"],
            "rule_name": r["rule_name"],
            "zone_id": r["zone_id"],
            "equipment_id": r["equipment_id"],
            "details": json.loads(r["details_json"]) if r["details_json"] else {},
        })
    return triggers


def build_payload(triggers: list[dict]) -> dict:
    """Compact JSON payload sent to Claude as the user message."""
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "trigger_count": len(triggers),
        "triggers": triggers,
    }


def _parse_response(raw_text: str) -> dict:
    """Claude is instructed to return raw JSON, but strip code fences
    defensively in case they slip in anyway."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Fall back gracefully so a malformed response never crashes the API route
        parsed = {"recommendation": raw_text.strip(), "priority": "medium"}

    parsed.setdefault("recommendation", "")
    parsed.setdefault("priority", "medium")
    return parsed


def _fallback_recommendation(payload: dict) -> dict:
    triggers = payload.get("triggers", [])
    if not triggers:
        return {
            "recommendation": "All gym zones and equipment are operating within normal capacity limits.",
            "priority": "low",
        }

    points = []
    has_high_priority = False
    for t in triggers:
        rule = t.get("rule_name")
        zone = (t.get("zone_id") or "main zone").replace("_", " ").title()
        eq = (t.get("equipment_id") or "equipment").replace("_", " ").title()
        details = t.get("details", {})

        if rule == "zone_imbalance":
            has_high_priority = True
            ratio = details.get("ratio", 2.0)
            points.append(f"High traffic imbalance detected in {zone} (load is {ratio}x higher than gym average). Recommend shifting portable equipment or opening overflow areas.")
        elif rule == "idle_equipment":
            idle_m = details.get("idle_minutes", 45)
            points.append(f"{eq} in {zone} has been idle for {idle_m} minutes during peak hours. Flagged for inspection for possible mechanical pin failure.")
        elif rule == "underused_zone":
            points.append(f"{zone} has experienced low utilization (<2 people avg). Consider repurposing area for functional bodyweight or stretching space.")
        elif rule == "peak_time_mismatch":
            points.append("Peak member arrival variance detected. Shift staff schedule by +1.5 hours to align with actual peak throughput.")

    narrative = " ".join(points) if points else "Operational parameters evaluated: minor adjustments suggested for space balancing."
    return {
        "recommendation": narrative,
        "priority": "high" if has_high_priority else "medium",
    }


def call_claude(payload: dict) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return _fallback_recommendation(payload)

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=MODEL,
            contents=f"{SYSTEM_PROMPT}\n\nInput data:\n{json.dumps(payload, ensure_ascii=False)}",
        )
        return _parse_response(response.text or "")
    except Exception as e:
        print(f"Gemini API call failed ({e}), using grounded rule fallback.")
        return _fallback_recommendation(payload)


def _save_recommendation(conn, result: dict, trigger_ids: list[int], report_type: str = "live") -> int:
    cursor = conn.execute(
        """INSERT INTO llm_recommendations (recommendation_text, based_on_triggers, report_type)
           VALUES (?, ?, ?)""",
        (result["recommendation"], json.dumps(trigger_ids), report_type),
    )
    conn.commit()
    return cursor.lastrowid


def _mark_resolved(conn, trigger_ids: list[int]) -> None:
    if not trigger_ids:
        return
    placeholders = ",".join("?" * len(trigger_ids))
    conn.execute(
        f"UPDATE rule_triggers SET resolved = 1 WHERE id IN ({placeholders})",
        trigger_ids,
    )
    conn.commit()


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------
def generate_recommendation() -> dict:
    """Reads unresolved rule_triggers, calls Claude, stores + returns
    the recommendation. Marks the triggers used as resolved so the
    same issue isn't re-reported every run."""
    conn = get_connection()
    try:
        triggers = _load_unresolved_triggers(conn)
        if not triggers:
            return {"status": "no_triggers", "recommendation": None}

        payload = build_payload(triggers)
        result = call_claude(payload)

        trigger_ids = [t["id"] for t in triggers]
        rec_id = _save_recommendation(conn, result, trigger_ids, report_type="live")
        _mark_resolved(conn, trigger_ids)

        return {
            "status": "ok",
            "recommendation_id": rec_id,
            "recommendation": result["recommendation"],
            "priority": result["priority"],
            "based_on_trigger_ids": trigger_ids,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    print(json.dumps(generate_recommendation(), indent=2, ensure_ascii=False))
