"""
email_sender.py
Person 2 — Backend Logic, Rules & LLM Integration

Sends staff-facing emails via Resend (resend.com):
    - live recommendation alerts (from llm_recommender.py)
    - monthly reports with the chart image attached (from report_generator.py)

Needs two env vars in backend/.env:
    RESEND_API_KEY=re_...
    GYM_STAFF_EMAIL=someone@example.com     # who receives alerts/reports
    ALERT_FROM_EMAIL=alerts@yourdomain.com  # must be a Resend-verified sender
                                             # (or onboarding@resend.dev for testing)

Entry points:
    send_recommendation_email(recommendation_text, priority)
    send_monthly_report_email(narrative, chart_path, year, month)
"""

import sys
import os
import base64
from pathlib import Path

try:
    import resend
    HAS_RESEND = True
except ImportError:
    HAS_RESEND = False

from dotenv import load_dotenv

sys.path.append(str(Path(__file__).resolve().parent.parent))

load_dotenv(override=True)


def _get_client_ready() -> tuple[str, str]:
    load_dotenv(override=True)
    api_key = os.environ.get("RESEND_API_KEY")
    staff_email = os.environ.get("GYM_STAFF_EMAIL")
    default_from = os.environ.get("ALERT_FROM_EMAIL", "onboarding@resend.dev")

    if not api_key:
        raise RuntimeError(
            "RESEND_API_KEY is not set. Add it to backend/.env "
            "(get a key at resend.com after verifying a sending domain)."
        )
    if not staff_email:
        raise RuntimeError(
            "GYM_STAFF_EMAIL is not set. Add it to backend/.env — "
            "this is who receives the alert/report emails."
        )
    resend.api_key = api_key
    return default_from, staff_email


def _priority_badge(priority: str) -> str:
    colors = {"high": "#dc2626", "medium": "#d97706", "low": "#16a34a"}
    color = colors.get(priority, "#6b7280")
    return (
        f'<span style="background:{color};color:white;padding:2px 10px;'
        f'border-radius:12px;font-size:12px;font-weight:600;text-transform:uppercase">'
        f"{priority}</span>"
    )


# ---------------------------------------------------------------------
# 1. Live recommendation alert (short, sent whenever a rule fires)
# ---------------------------------------------------------------------
def send_recommendation_email(recommendation_text: str, priority: str = "medium") -> dict:
    default_from, staff_email = _get_client_ready()

    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 560px; margin: auto;">
        <h2 style="margin-bottom: 4px;">Smart Gym — New Recommendation</h2>
        <p style="margin-top: 0;">{_priority_badge(priority)}</p>
        <p style="line-height: 1.6; color: #111;">{recommendation_text}</p>
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
        <p style="color: #6b7280; font-size: 13px;">
            Automated alert from the Smart Gym Monitoring System.
        </p>
    </div>
    """

    params: resend.Emails.SendParams = {
        "from": default_from,
        "to": [staff_email],
        "subject": f"[Smart Gym] {priority.upper()} priority recommendation",
        "html": html,
    }
    return resend.Emails.send(params)


# ---------------------------------------------------------------------
# 2. Monthly report (narrative + chart attachment)
# ---------------------------------------------------------------------
def _encode_attachment(file_path: Path) -> dict:
    with open(file_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()
    return {"filename": file_path.name, "content": content_b64}


def send_monthly_report_email(narrative: str, chart_path: str | None,
                               year: int, month: int) -> dict:
    default_from, staff_email = _get_client_ready()

    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 560px; margin: auto;">
        <h2 style="margin-bottom: 4px;">Smart Gym — Monthly Report ({year}-{month:02d})</h2>
        <p style="line-height: 1.6; color: #111;">{narrative}</p>
        {"<p style='color:#6b7280;font-size:13px;'>Occupancy chart attached.</p>" if chart_path else ""}
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
        <p style="color: #6b7280; font-size: 13px;">
            Automated monthly report from the Smart Gym Monitoring System.
        </p>
    </div>
    """

    params: resend.Emails.SendParams = {
        "from": default_from,
        "to": [staff_email],
        "subject": f"[Smart Gym] Monthly Report — {year}-{month:02d}",
        "html": html,
    }

    if chart_path and Path(chart_path).exists():
        params["attachments"] = [_encode_attachment(Path(chart_path))]

    result = resend.Emails.send(params)
    # Expose who it actually went to, so the frontend can show the real
    # recipient instead of guessing or hardcoding a name.
    if isinstance(result, dict):
        result["sent_to"] = staff_email
    return result


if __name__ == "__main__":
    # Quick manual test — requires RESEND_API_KEY + GYM_STAFF_EMAIL in .env
    result = send_recommendation_email(
        "Squat rack 1 has been idle for over 80 minutes during open hours. "
        "Consider checking if it's out of service or reallocating floor space.",
        priority="medium",
    )
    print(result)
