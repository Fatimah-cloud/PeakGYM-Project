"""
routers/recommendations.py
Person 2 — Backend Logic, Rules & LLM Integration

Endpoint: latest LLM recommendation + monthly report.
"""

import sys
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

sys.path.append(str(Path(__file__).resolve().parent.parent))
from database import get_connection  # noqa: E402
from services.llm_recommender import generate_recommendation  # noqa: E402
from services.report_generator import generate_monthly_report  # noqa: E402
from services.email_sender import send_recommendation_email, send_monthly_report_email  # noqa: E402

router = APIRouter()


@router.get("/latest")
def latest_recommendation():
    """Most recent live recommendation (report_type='live')."""
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT * FROM llm_recommendations
               WHERE report_type = 'live'
               ORDER BY timestamp DESC LIMIT 1"""
        ).fetchone()
        if not row:
            return {"recommendation": None}
        return {
            "id": row["id"],
            "timestamp": row["timestamp"],
            "recommendation": row["recommendation_text"],
            "based_on_triggers": json.loads(row["based_on_triggers"] or "[]"),
        }
    finally:
        conn.close()


@router.post("/generate")
def trigger_recommendation():
    """Force-generate a recommendation right now from any unresolved rule
    triggers (normally scheduler.py does this hourly). Useful for the demo
    dashboard's "refresh" button."""
    result = generate_recommendation()
    if result.get("status") == "no_triggers":
        return {"status": "no_triggers", "message": "No unresolved rule triggers to act on."}
    if result.get("status") != "ok":
        raise HTTPException(status_code=502, detail="Recommendation generation failed")
    return result


@router.post("/send-monthly-email")
def send_monthly_email():
    """Generate the monthly report and send it immediately via Resend email.
    Called by the 'Send via Email' button in the Monthly Intelligence Report modal."""
    try:
        report = generate_monthly_report()
        if report.get("status") == "no_data":
            return {"status": "no_data", "message": "No data available yet for the report period."}

        result = send_monthly_report_email(
            narrative=report.get("narrative", "No narrative generated."),
            chart_path=report.get("chart_path"),
            year=report.get("year"),
            month=report.get("month"),
        )
        return {"status": "sent", "result": result, "sent_to": result.get("sent_to") if isinstance(result, dict) else None}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Email failed: {e}")


@router.get("/monthly-report")
def latest_monthly_report():
    """Most recent monthly report (report_type='monthly')."""
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT * FROM llm_recommendations
               WHERE report_type = 'monthly'
               ORDER BY timestamp DESC LIMIT 1"""
        ).fetchone()
        if not row:
            return {"report": None}
        return {
            "id": row["id"],
            "generated_at": row["timestamp"],
            "narrative": row["recommendation_text"],
            "period": json.loads(row["based_on_triggers"] or "{}"),
        }
    finally:
        conn.close()


@router.post("/monthly-report/generate")
def trigger_monthly_report():
    """Force-generate the monthly report now (normally runs on the 1st via
    scheduler.py). Defaults to summarizing last month."""
    result = generate_monthly_report()
    if result.get("status") == "no_data":
        return {"status": "no_data", "message": "No hourly_stats data for that period yet."}
    return result
